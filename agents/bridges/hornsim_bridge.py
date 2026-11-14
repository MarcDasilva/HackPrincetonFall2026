"""Bridge from the agents' evaluator contract to the backend's hornsim pipeline.

Run with the backend interpreter and the backend on the import path, never with
the agents environment:

    PYTHONPATH=backend backend/.venv/bin/python agents/bridges/hornsim_bridge.py <command>

One JSON object is read from stdin and one is written to stdout.
Everything hornsim and its libraries print goes to stderr.

Commands
    describe       what the installed hornsim code supports (bounds, levels, clips, version)
    context        build the patient context once per (ear mesh, audiogram)
    build          build one aid and its acoustics once per (context, design numbers)
    score          HASPI v2 for one listening condition, aided or unaided
    template-ear   write AudioEar's average ear as a mesh, for runs without a photo

This file is glue. The geometry, the acoustic model, and the scoring are
hornsim's own functions, called the way backend/app/jobs.py and
hornsim/score.py call them. Nothing here rescales a level or fills in a
hearing threshold. A clip type with several clips (three clean, four in
babble) is scored clip by clip and averaged, the same way for both types.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.metadata
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Iterator
from typing import Any

BUILD_MARKER = "bridge_build.json"
CONTEXT_MARKER = "bridge_context.json"
CLIP_TYPES = ("clean", "babble")


class BridgeError(Exception):
    """A problem to report to the caller as a structured error, not a traceback."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def backend_dir() -> str:
    import hornsim

    return os.path.dirname(os.path.dirname(os.path.abspath(hornsim.__file__)))


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def key_of(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_json_atomic(path: str, value: Any) -> None:
    handle, temp_name = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=1)
    os.replace(temp_name, path)


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


@contextlib.contextmanager
def locked(path: str) -> Iterator[None]:
    """Hold an exclusive lock so two processes never build the same thing at once."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _git(backend: str, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", backend, *args], capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def hornsim_version(backend: str) -> str:
    """Identify the hornsim code: the last commit that touched it, or a hash of its sources."""
    sha = _git(backend, "log", "-1", "--format=%h", "--", "hornsim")
    if sha:
        dirty = _git(backend, "status", "--porcelain", "--", "hornsim")
        return f"hornsim-{sha}" + ("-dirty" if dirty else "")
    digest = hashlib.sha256()
    folder = os.path.join(backend, "hornsim")
    for name in sorted(os.listdir(folder)):
        if name.endswith((".py", ".yaml")):
            digest.update(name.encode("utf-8"))
            with open(os.path.join(folder, name), "rb") as stream:
                digest.update(stream.read())
    return f"hornsim-src-{digest.hexdigest()[:12]}"


def number_key(value: float) -> int | float:
    """Audiogram keys the way backend/app/jobs.py writes them: whole frequencies as ints."""
    return int(value) if float(value) == int(value) else float(value)


# --------------------------------------------------------------------------
# describe
# --------------------------------------------------------------------------


def aid_design_fields() -> dict[str, dict[str, float]]:
    """Parameter bounds and defaults of the server's AidDesign model (backend/app/main.py)."""
    with tempfile.TemporaryDirectory() as scratch:
        # Importing the server module creates its data folder. Point that at scratch space.
        previous = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = scratch
        try:
            from app.main import AidDesign
        finally:
            if previous is None:
                os.environ.pop("DATA_DIR", None)
            else:
                os.environ["DATA_DIR"] = previous
    fields: dict[str, dict[str, float]] = {}
    for name, schema in AidDesign.model_json_schema()["properties"].items():
        fields[name] = {
            key: schema[key] for key in ("default", "minimum", "maximum") if schema.get(key) is not None
        }
    return fields


def mesh_info(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise BridgeError("ear_mesh_missing", f"The ear mesh '{path}' does not exist.")
    info: dict[str, Any] = {"file_name": os.path.basename(path), "sha256": file_sha256(path)}
    sidecar = path + ".provenance.json"
    if os.path.isfile(sidecar):
        info["provenance"] = read_json(sidecar)
    return info


def cmd_describe(payload: dict[str, Any]) -> dict[str, Any]:
    from clarity.evaluator.haspi.haspi import HASPI_AUDIOGRAM_FREQUENCIES
    from hornsim import aid, context, score, scoring

    backend = backend_dir()
    cfg = context.load_defaults()
    speech, canal = cfg["speech"], cfg["canal"]
    clips = [{"name": f"clean_{i + 1}", "type": "clean"} for i in range(len(speech["clean"]))]
    clips += [
        {"name": f"babble_{i + 1}", "type": "babble", "snr_db": item["snr_db"]}
        for i, item in enumerate(speech["noisy"])
    ]
    described: dict[str, Any] = {
        "version": hornsim_version(backend),
        "dependencies": {"pyclarity": importlib.metadata.version("pyclarity")},
        "aid_design_fields": aid_design_fields(),
        "aid_defaults": dict(aid.DEFAULT),
        "levels_db_spl": list(cfg["evaluation"]["levels_db_spl"]),
        "clips": clips,
        "babble_talkers": len(speech["babble_voices"]),
        "haspi_seed": cfg["evaluation"]["haspi_seed"],
        # The level hornsim.scoring holds HASPI's clean reference at, whatever the presentation level.
        "reference_db_spl": scoring.REFERENCE_DB_SPL,
        "haspi_frequencies_hz": [float(f) for f in HASPI_AUDIOGRAM_FREQUENCIES],
        "hornsim_haspi_frequencies_hz": [float(f) for f in scoring.HASPI_FREQS],
        "ceiling_prescriptions": list(cfg["evaluation"]["ceiling_prescriptions"]),
        "canal": {
            "residual_volume_cc": list(canal["residual_volume_cc"]),
            "samples": canal["samples"],
            "scored": inspect.signature(score.score).parameters["n_canals"].default,
            "assumed_diameter_mm": cfg["ear_world"]["canal_opening_diameter_mm"],
        },
    }
    if payload.get("ear_mesh"):
        described["ear_mesh"] = mesh_info(payload["ear_mesh"])
    return described


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------


def cmd_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the patient context once per (mesh, height, side, audiogram, code version)."""
    from hornsim import context

    started = time.time()
    backend = backend_dir()
    work = payload["work_dir"]
    mesh = payload["ear_mesh"]
    info = mesh_info(mesh)
    audiogram = {number_key(float(f)): float(v) for f, v in payload["audiogram_db_hl"].items()}
    identity = {
        "version": hornsim_version(backend),
        "pyclarity": importlib.metadata.version("pyclarity"),
        "ear_mesh_sha256": info["sha256"],
        "ear_height_mm": payload.get("ear_height_mm"),
        "side": payload["side"],
        "audiogram_db_hl": {str(f): v for f, v in sorted(audiogram.items())},
    }
    key = key_of(identity)
    out = os.path.join(work, "contexts", key)
    marker = os.path.join(out, CONTEXT_MARKER)

    with locked(os.path.join(work, "contexts", f"{key}.lock")):
        reused = os.path.isfile(marker)
        if not reused:
            # Keep our own copy of the mesh: hornsim.aid reads it again from the path in context.json.
            stored = os.path.join(work, "meshes", info["sha256"][:16] + os.path.splitext(mesh)[1])
            if not os.path.isfile(stored):
                os.makedirs(os.path.dirname(stored), exist_ok=True)
                shutil.copyfile(mesh, stored + ".tmp")
                os.replace(stored + ".tmp", stored)
            shutil.rmtree(out, ignore_errors=True)

            cfg = context.load_defaults()
            # The audiogram is the caller's, as given. The placeholder in defaults.yaml is never used.
            cfg["patient"].update(
                {
                    "id": key,
                    "ear_mesh": stored,
                    "ear_height_mm": payload.get("ear_height_mm"),
                    "side": payload["side"],
                    "audiogram_db_hl": audiogram,
                }
            )
            cfg["ear_world"]["landmarks_xlsx"] = os.path.normpath(
                os.path.join(context.HERE, cfg["ear_world"]["landmarks_xlsx"])
            )
            context.build(cfg, out, log=log)
            write_json_atomic(marker, {"identity": identity, "built_at": time.time()})

    saved = read_json(os.path.join(out, "context.json"))
    return {
        "version": identity["version"],
        "context_key": key,
        "context_dir": out,
        "reused": reused,
        "seconds": round(time.time() - started, 3),
        "audiogram_db_hl": saved["config"]["patient"]["audiogram_db_hl"],
        "ear_mesh": info,
        "ear_world": {
            name: saved["ear_world"][name]
            for name in ("bowl_volume_cc", "shell_volume_cc", "opening_area_mm2", "max_depth_mm")
        },
        "assets": {
            "references_json": os.path.join(out, "references.json"),
            "canals_json": os.path.join(out, "canals.json"),
            "ear_world_glb": os.path.join(out, "ear_world.glb"),
            "context_summary_png": os.path.join(out, "summary.png"),
        },
    }


def require_context(context_dir: str) -> None:
    if not os.path.isfile(os.path.join(context_dir, CONTEXT_MARKER)):
        raise BridgeError("context_missing", f"No finished patient context at '{context_dir}'.")


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def cmd_build(payload: dict[str, Any]) -> dict[str, Any]:
    """Build one aid and model its acoustics, once per (context, design numbers, code version)."""
    from hornsim import acoustics, aid

    started = time.time()
    work, context_dir = payload["work_dir"], payload["context_dir"]
    require_context(context_dir)
    overrides = {name: float(value) for name, value in payload["parameters"].items()}
    version = hornsim_version(backend_dir())
    design_numbers = {**aid.DEFAULT, **overrides}
    key = key_of({"version": version, "context": os.path.basename(context_dir), "design": design_numbers})
    patient = os.path.join(work, "candidates", key)
    aid_dir = os.path.join(patient, "aid")
    marker = os.path.join(patient, BUILD_MARKER)

    with locked(os.path.join(work, "candidates", f"{key}.lock")):
        reused = os.path.isfile(marker)
        if not reused:
            shutil.rmtree(patient, ignore_errors=True)
            os.makedirs(patient)
            # hornsim expects <patient>/context and <patient>/aid side by side.
            os.symlink(os.path.abspath(context_dir), os.path.join(patient, "context"))
            record: dict[str, Any] = {"version": version, "candidate_key": key, "parameters": overrides}
            try:
                design = aid.build(os.path.join(patient, "context"), aid_dir, overrides, log=log)
            except ValueError as error:
                # hornsim.aid itself raises ValueError when no bore or vent route fits this ear,
                # including a throat too wide for the canal tip and a vent that cannot clear the bore.
                # A ValueError from deeper down (a mesh library) is a crash, not a verdict on fit.
                raised_in = traceback.extract_tb(error.__traceback__)[-1].filename
                if os.path.abspath(raised_in) != os.path.abspath(inspect.getfile(aid)):
                    raise
                record["fits"] = False
                record["error"] = str(error)
            else:
                summary = acoustics.evaluate(patient, log=log)["summary"]
                record["fits"] = True
                record["design"] = {k: v for k, v in design.items() if k != "acoustic"}
                record["acoustics_summary"] = summary
            record["build_seconds"] = round(time.time() - started, 3)
            write_json_atomic(marker, record)

    record = read_json(marker)
    result: dict[str, Any] = {
        "version": record["version"],
        "candidate_key": key,
        "candidate_dir": patient,
        "reused": reused,
        "fits": record["fits"],
        "seconds": round(time.time() - started, 3),
        "build_seconds": record["build_seconds"],
    }
    if not record["fits"]:
        result["error"] = record["error"]
        return result
    result["design"] = record["design"]
    result["acoustics_summary"] = record["acoustics_summary"]
    result["assets"] = {
        "design_json": os.path.join(aid_dir, "design.json"),
        "aid_glb": os.path.join(aid_dir, "aid.glb"),
        "aid_in_ear_glb": os.path.join(aid_dir, "aid_in_ear.glb"),
        "aid_print_stl": os.path.join(aid_dir, "aid_print.stl"),
        "acoustics_json": os.path.join(aid_dir, "acoustics.json"),
        "insertion_gain_png": os.path.join(aid_dir, "insertion_gain.png"),
    }
    return result


# --------------------------------------------------------------------------
# score
# --------------------------------------------------------------------------


def cmd_score(payload: dict[str, Any]) -> dict[str, Any]:
    """HASPI v2 for one clip type at one presentation level.

    Follows hornsim.score.score step for step (same canal spread, same clip
    files, same calls), but for one condition at a time, for every condition
    in references.json rather than only those with headroom, and with the
    unaided case sent through the same path with a flat 0 dB response.
    """
    import numpy as np
    import soundfile as sf
    from hornsim import acoustics as ac
    from hornsim import score, scoring
    from hornsim.audio import apply_gain, rms

    started = time.time()
    context_dir, candidate_dir = payload["context_dir"], payload.get("candidate_dir")
    clip_type, level = payload["clip_type"], payload["level_db_spl"]
    require_context(context_dir)
    if clip_type not in CLIP_TYPES:
        raise BridgeError("unknown_clip_type", f"Clip type '{clip_type}' is not one of {CLIP_TYPES}.")

    cfg = read_json(os.path.join(context_dir, "context.json"))["config"]
    refs = read_json(os.path.join(context_dir, "references.json"))
    canal_file = read_json(os.path.join(context_dir, "canals.json"))
    audiogram = scoring.audiogram(cfg["patient"]["audiogram_db_hl"])
    seed = refs["seed"]
    rows = [
        row
        for row in refs["results"]
        if row["clip"].startswith(clip_type + "_") and row["level_db_spl"] == level
    ]
    if not rows:
        raise BridgeError(
            "unknown_condition", f"references.json has no '{clip_type}' clip at {level} dB SPL."
        )

    # The spread of canals hornsim.score uses (smallest to largest), not all of them.
    n_canals = inspect.signature(score.score).parameters["n_canals"].default
    sampled = canal_file["canals"]
    picks = np.unique(np.round(np.linspace(0, len(sampled) - 1, n_canals)).astype(int))
    canals = [ac.Canal(sampled[i]["volume_cc"], canal_file["assumed_diameter_mm"]) for i in picks]
    freqs = ac.DEFAULT_FREQS
    flat = np.zeros(len(freqs))
    gains = None
    if candidate_dir is not None:
        if not os.path.isfile(os.path.join(candidate_dir, BUILD_MARKER)):
            raise BridgeError("candidate_missing", f"No finished aid build at '{candidate_dir}'.")
        design = ac.Design.from_design_json(read_json(os.path.join(candidate_dir, "aid", "design.json")))
        gains = ac.insertion_gain_db(design, canals, freqs)

    unaided_dir = os.path.join(context_dir, "bridge_unaided")
    os.makedirs(unaided_dir, exist_ok=True)
    per_clip = []
    for row in rows:
        name = row["clip"]
        reference, fs = sf.read(os.path.join(context_dir, "speech", f"{name}_reference.wav"))
        heard, _ = sf.read(os.path.join(context_dir, "speech", f"{name}_input.wav"))
        # hornsim stores clips scaled down and hornsim.score restores "reference RMS = 1" on
        # reading. That is the calibration convention itself, repeated here unchanged.
        k = 1 / rms(reference)
        reference, heard = reference * k, heard * k

        unaided_path = os.path.join(unaided_dir, f"{name}_{level}.json")
        if os.path.isfile(unaided_path):
            unaided = read_json(unaided_path)["haspi"]
        else:
            unaided = scoring.haspi(reference, apply_gain(heard, fs, freqs, flat), fs, audiogram, level, seed)
            write_json_atomic(unaided_path, {"clip": name, "level_db_spl": level, "haspi": unaided})

        entry: dict[str, Any] = {
            "clip": name,
            "unaided_haspi": unaided,
            # hornsim's own references for this condition, computed when the context was built.
            "references": {
                key: row[key]
                for key in (
                    "unaided",
                    "ceiling",
                    "ceiling_from",
                    "headroom",
                    "use_in_reward",
                    "healthy_check",
                )
            },
        }
        if gains is not None:
            entry["aided_haspi_per_canal"] = [
                scoring.haspi(reference, apply_gain(heard, fs, freqs, gain), fs, audiogram, level, seed)
                for gain in gains
            ]
        per_clip.append(entry)

    unaided_mean = float(np.mean([entry["unaided_haspi"] for entry in per_clip]))
    if gains is None:
        # A flat response does not depend on the canal, so every canal has the same score.
        mean = worst = unaided_mean
    else:
        by_canal = np.mean([entry["aided_haspi_per_canal"] for entry in per_clip], axis=0)
        mean, worst = float(np.mean(by_canal)), float(np.min(by_canal))
    return {
        "version": hornsim_version(backend_dir()),
        "clip_type": clip_type,
        "level_db_spl": level,
        "haspi_mean": mean,
        "haspi_worst_canal": worst,
        "unaided_haspi_mean": unaided_mean,
        "canals_used_cc": [canal.volume_cc for canal in canals],
        "haspi_seed": seed,
        "per_clip": per_clip,
        "seconds": round(time.time() - started, 3),
    }


# --------------------------------------------------------------------------
# template-ear
# --------------------------------------------------------------------------


def cmd_template_ear(payload: dict[str, Any]) -> dict[str, Any]:
    """Write AudioEar's average ear, posed and scaled the way earrecon writes ear.ply.

    This is the ear model's mean shape (all shape coefficients zero) put
    through the same centring, axis flips, and height scaling as
    backend/earrecon/reconstruct.py. It needs no photo and no network weights.
    It is a template, not anyone's ear.
    """
    import pickle

    import numpy as np
    import trimesh

    out = os.path.abspath(payload["out"])
    height_mm = float(payload.get("height_mm", 62.0))
    side = payload.get("side", "right")
    if side not in ("left", "right"):
        raise BridgeError("bad_side", "side must be 'left' or 'right'.")
    backend = backend_dir()
    audioear = os.environ.get("AUDIOEAR_DIR", os.path.join(backend, "third_party", "AudioEar"))
    model_path = os.path.join(audioear, "data", "UHM_models", "ear_model.pkl")
    if not os.path.isfile(model_path):
        raise BridgeError(
            "audioear_missing",
            f"'{model_path}' is missing. Run 'git submodule update --init' in the repository.",
        )
    with open(model_path, "rb") as stream:
        model = pickle.load(stream)
    verts = np.asarray(model["Mean"], dtype=float)[:, 0].reshape(-1, 3)
    faces = np.asarray(model["Trilist"], dtype=np.int64)
    if faces.min() == 1:
        faces = faces - 1
    verts = verts - (verts.min(0) + verts.max(0)) / 2
    verts[:, 0] *= -1
    verts[:, 2] *= -1
    verts = verts * (height_mm / np.ptp(verts[:, 1]))
    if side == "left":
        verts[:, 2] *= -1
        faces = faces[:, ::-1]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    trimesh.Trimesh(verts, faces, process=False).export(out)
    provenance = {
        "source": "AudioEar average ear (mean of the ear shape model, no photo). A template, not a person's ear.",
        "height_mm": height_mm,
        "side": side,
        "audioear_commit": _git(audioear, "rev-parse", "--short", "HEAD"),
    }
    write_json_atomic(out + ".provenance.json", provenance)
    return {"ear_mesh": out, "sha256": file_sha256(out), "provenance": provenance}


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

COMMANDS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "describe": cmd_describe,
    "context": cmd_context,
    "build": cmd_build,
    "score": cmd_score,
    "template-ear": cmd_template_ear,
}


def main(argv: list[str]) -> int:
    # Keep stdout for the one JSON answer. Anything else printed lands on stderr.
    answer_fd = os.dup(1)
    os.dup2(2, 1)
    code = 0
    try:
        if len(argv) != 2 or argv[1] not in COMMANDS:
            raise BridgeError("usage", f"usage: hornsim_bridge.py <{'|'.join(COMMANDS)}> with JSON on stdin")
        payload = json.load(sys.stdin)
        answer = {"ok": True, **COMMANDS[argv[1]](payload)}
    except BridgeError as error:
        answer = {"ok": False, "error": {"code": error.code, "message": str(error)}}
    except Exception as error:
        traceback.print_exc()
        answer = {
            "ok": False,
            "error": {"code": "bridge_crashed", "message": f"{type(error).__name__}: {error}"[:1000]},
        }
        code = 1
    sys.stdout.flush()
    with os.fdopen(answer_fd, "w", encoding="utf-8") as stream:
        json.dump(answer, stream, default=float)
        stream.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
