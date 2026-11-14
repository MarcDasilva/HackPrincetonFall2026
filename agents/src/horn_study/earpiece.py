"""The final step: turn a completed study's selected design into a printable earpiece.

    horn-study earpiece <study_id> --patient-dir <backend patient dir>

Everything the study evaluated is LOCKED: throat and mouth area, the canal stem length, the bore
flare, and whether there is a collector with its reach and opening area. A study verifies one
specific shape against the unaided ear, so changing any of these afterwards would print a design
nobody tested. The model only sets what the acoustic score does not see: which way the collector
faces and its outline, the talker side, the hood on a flush piece, how the mouth follows the
concha, and the removal tab. Once the model chooses, code builds the S and L
sizes of that same design: nobody yet knows how far a photo-built ear is off, so the patient tries
all three. The bore length is not a dial: the horn is carved inside the concha, so the depth of the
bowl sets it.
Every build runs the backend's geometry checks, and a build the checks rejected can never be
chosen. The geometry lives in the backend (`backend/hornsim/earpiece.py`), which has its own
environment, so builds run as a subprocess.

The evaluator's design family must name its parameters `throat_mm2` and `mouth_mm2` (or
`*_diameter_mm`) for them to carry over; anything else is recorded but not used.
"""

from __future__ import annotations

import base64
import json
import math
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

BACKEND_DIR_ENV = "HORN_STUDY_BACKEND_DIR"
BACKEND_PYTHON_ENV = "HORN_STUDY_BACKEND_PYTHON"
OUTPUT_NAME = "earpiece.json"

Builder = Callable[[Path, dict[str, Any], str], dict[str, Any]]


class EarpieceError(Exception):
    pass


def _backend() -> tuple[str, Path]:
    root = Path(os.environ.get(BACKEND_DIR_ENV) or Path(__file__).resolve().parents[3] / "backend")
    venv = root / ".venv" / "bin" / "python"
    return os.environ.get(BACKEND_PYTHON_ENV) or (str(venv) if venv.exists() else "python3"), root


def backend_build(patient_dir: Path, params: dict[str, Any], design_id: str) -> dict[str, Any]:
    """One build through the backend CLI. A crash comes back as a failed build, never a success."""
    python, root = _backend()
    proc = subprocess.run(
        [python, "-m", "hornsim.earpiece", str(patient_dir), json.dumps(params), design_id],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "reasons": [{"check": "backend_error", "message": proc.stderr[-600:]}]}
    return json.loads(proc.stdout)


def describe_dials() -> dict[str, Any]:
    python, root = _backend()
    out = subprocess.run(
        [python, "-m", "hornsim.earpiece", "--describe"], cwd=root, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


COLLECTOR_REACH = "collector_reach_mm"
COLLECTOR_OPENING = "collector_mouth_mm2"
SECTION_POINTS = 12
MIN_OUTWARD = 0.5  # a collector must grow away from the head: at least this share of its reach
# The dials the acoustic score responds to. A study that did not set one evaluated the builder's
# default for it, so that default is what gets locked.
ACOUSTIC_DIALS = ("canal_stem_mm", "flare_mid1", "flare_mid2")


def locked_params(parameters: dict[str, Any], dials: dict[str, Any] | None = None) -> dict[str, float]:
    """Every number the study evaluated, converted to the builder's names.

    Throat and mouth always. The canal stem and the flare too: from the study when it set them,
    otherwise the builder's default, which is what the study's evaluation used.
    """
    out: dict[str, float] = {}
    for part in ("throat", "mouth"):
        if f"{part}_mm2" in parameters:
            out[f"{part}_mm2"] = float(parameters[f"{part}_mm2"])
        elif f"{part}_diameter_mm" in parameters:
            out[f"{part}_mm2"] = round(math.pi * (float(parameters[f"{part}_diameter_mm"]) / 2) ** 2, 2)
    for name in ACOUSTIC_DIALS:
        if name in parameters:
            out[name] = float(parameters[name])
        elif dials and isinstance(dials.get(name), dict) and "default" in dials[name]:
            out[name] = float(dials[name]["default"])
    return out


def study_collector(parameters: dict[str, Any]) -> tuple[float, float] | None:
    """(reach mm, opening mm^2) of the collector the study evaluated.

    None when the study's family has no collector dials. (0, 0) when it has them and the selected
    design is flush.
    """
    if COLLECTOR_REACH not in parameters and COLLECTOR_OPENING not in parameters:
        return None
    return float(parameters.get(COLLECTOR_REACH, 0.0)), float(parameters.get(COLLECTOR_OPENING, 0.0))


def lock_collector(
    requested: dict[str, Any] | None, studied: tuple[float, float] | None
) -> dict[str, Any] | None:
    """The collector to build: the model's direction and outline at the study's reach and opening.

    The acoustic model sees a collector only as area along its length, so the model may turn it
    toward the talker and shape its rim, while its length and opening area stay the ones the study
    tested. With no collector in the study, none is built. When the study's family has no
    collector dials at all, the model's own collector passes through unchanged.
    """
    if studied is None:
        return requested
    reach, opening = studied
    if reach <= 0 or opening <= 0:
        return None
    spine = (requested or {}).get("spine") or [[1.0, 0.0, 0.0]]
    sections = (requested or {}).get("sections") or [[1.0] * SECTION_POINTS]
    try:
        end = [float(v) for v in spine[-1]][:3]
        radii = [abs(float(r)) for r in sections[-1]][:SECTION_POINTS]
    except (TypeError, ValueError, IndexError):
        end, radii = [1.0, 0.0, 0.0], [1.0] * SECTION_POINTS
    end += [0.0] * (3 - len(end))
    radii += [radii[-1] if radii else 1.0] * (SECTION_POINTS - len(radii))
    length = math.sqrt(sum(v * v for v in end))
    unit = [v / length for v in end] if length > 0 else [1.0, 0.0, 0.0]
    if unit[0] < MIN_OUTWARD:
        side = math.sqrt(unit[1] ** 2 + unit[2] ** 2) or 1.0
        keep = math.sqrt(1 - MIN_OUTWARD**2) / side
        unit = [MIN_OUTWARD, unit[1] * keep, unit[2] * keep]
    mean_square = sum(r * r for r in radii) / SECTION_POINTS
    scale = math.sqrt(opening / (math.pi * mean_square)) if mean_square > 0 else 0.0
    if scale <= 0:
        radii, scale = [1.0] * SECTION_POINTS, math.sqrt(opening / math.pi)
    return {
        "spine": [[round(reach * u, 3) for u in unit]],
        "sections": [[round(r * scale, 3) for r in radii]],
    }


def departures(
    geometry: dict[str, Any], locked: dict[str, float], studied: tuple[float, float] | None
) -> list[str]:
    """Where a built piece differs from what the study evaluated. Empty means it matches."""
    found: list[str] = []

    def compare(label: str, built: Any, wanted: float, tolerance: float, unit: str) -> None:
        if not isinstance(built, (int, float)) or isinstance(built, bool):
            return
        if abs(float(built) - wanted) > tolerance:
            found.append(f"{label}: built {float(built):g} {unit}, study evaluated {wanted:g} {unit}")

    for name, unit in (("throat_mm2", "mm^2"), ("mouth_mm2", "mm^2"), ("canal_stem_mm", "mm")):
        if name in locked:
            compare(name, geometry.get(name), locked[name], max(0.02 * locked[name], 0.05), unit)
    if studied is not None:
        _, opening = studied
        built_opening = geometry.get("collector_mouth_mm2")
        if opening <= 0 and geometry.get("collector"):
            found.append("collector: built one, but the study evaluated a flush piece")
        elif opening > 0:
            if not geometry.get("collector"):
                found.append("collector: none built, but the study evaluated one")
            else:
                compare("collector opening", built_opening, opening, 0.03 * opening, "mm^2")
    return found


SYSTEM = """You design the 3D earpiece for one patient after the study has chosen its acoustic numbers.

The piece has two parts. The SEAT sits in the bowl of the ear like an in-the-ear hearing aid: code
casts it from the patient's ear and carves the bore through it, from a soft stem in the canal up to
a mouth on the faceplate. The COLLECTOR is yours to design: an optional shape that grows out of that
mouth, away from the head. It can be a cone, a trumpet bell, a scoop that opens toward the main
talker, a flattened slot, an asymmetric petal, whatever this patient's needs call for. A bigger,
longer collector gathers more sound and is more visible; no collector (a flush faceplate) is the
most discreet. Match it to the person: what they listen to, where the talker is, and how visible a
device they would accept. Make each design specific to this patient, not a default.

Collector format: {"spine": [[out, up, front], ...], "sections": [[12 radii], ...]}, in mm from the
mouth centre. out = straight away from the head, up, front = toward the face. Each section lists the
INNER radius at 12 angles starting at front and turning toward up (front, 30, 60, up, 120, 150, back,
210, 240, down, 300, 330), one section per spine point; the mouth is the start. 1-8 spine points,
radii 1-30 mm, out >= 0, nothing more than 35 mm from the mouth. A cone: spine [[6,0,0],[14,0,0]],
sections [[9]*12, [13]*12]. A scoop toward the front: bend the spine forward and make the back of the
last section larger than the front, so a lip shelters the side away from the talker. A collector
replaces the hood (set hood_mm 0).

You also set: where the main talker is (aim), the hood when there is no collector, how closely the
mouth follows this concha's opening and its stretch, and where the removal tab sits.

The study tested one specific shape against the unaided ear, and everything it tested is fixed:
throat and mouth area, the canal stem length, how the bore widens (flare), and the collector's
reach and opening area, or the absence of a collector. `fixed_by_study` in the brief lists them.
Code applies those values whatever you send, so the printed piece is the one that was tested. For
the collector you choose the direction it faces and the outline of its rim: code keeps your
direction and the proportions of your last section, and sets its length and opening area to the
study's. Only the last spine point and section are used. When the study chose a flush piece, no
collector is built. If the patient's needs call for something the fixed values rule out, such as
a stem for grip, do not work around it: say so in your explanation, so it can be tested in a new
study.

Each build returns its checks and a picture of the piece in the ear. Look at the picture. When a
build fails, its reasons say what to move and which way; make the smallest change that fixes it.
Do not set the fit size; S, M and L prints are made after you finish.

Call build_earpiece for each attempt with a one-line reason. When a build succeeds and suits the
patient, call finish with its design_id and one plain sentence for the screen. You have a fixed
number of builds."""


def _with_preview(text: str, new_builds: list[dict[str, Any]]) -> Any:
    """The build's picture rides along with its numbers. Without it the model designs blind: it can
    pass every check and still choose a shape it never saw."""
    png = new_builds[0]["report"].get("files", {}).get("preview.png") if new_builds else None
    if not png or not Path(png).exists():
        return text
    data = base64.b64encode(Path(png).read_bytes()).decode()
    return [
        {"type": "text", "text": text},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
    ]


def brief(results: dict[str, Any], patient_dir: Path, locked: dict[str, float], dials: dict[str, Any]) -> str:
    context_path = patient_dir / "context" / "context.json"
    ear = {}
    if context_path.exists():
        cfg = json.loads(context_path.read_text(encoding="utf-8")).get("config", {})
        ear = {
            "side": cfg.get("patient", {}).get("side"),
            "ear_height_mm": cfg.get("patient", {}).get("ear_height_mm"),
        }
    fixed = {"throat_mm2", "mouth_mm2", "wall_mm", *locked}
    shaping = {k: v for k, v in dials.items() if k not in fixed}
    studied = study_collector(results["selected_candidate"].get("parameters", {}))
    fixed_by_study: dict[str, Any] = dict(locked)
    if studied is not None:
        fixed_by_study["collector"] = (
            {"reach_mm": studied[0], "opening_mm2": studied[1]}
            if studied[0] > 0 and studied[1] > 0
            else "none: the study chose a flush piece"
        )
    return json.dumps(
        {
            "selected_candidate": {
                k: results["selected_candidate"].get(k) for k in ("candidate_id", "label", "rationale")
            },
            "fixed_by_study": fixed_by_study,
            "patient_context": results.get("study_context"),
            "ear": ear,
            "dials_you_set": shaping,
        },
        indent=1,
    )


def produce_earpiece(
    study_dir: Path,
    patient_dir: Path,
    model: BaseChatModel,
    *,
    build: Builder = backend_build,
    dials: dict[str, Any] | None = None,
    max_builds: int = 4,
) -> dict[str, Any]:
    """Run the shaping agent for one finished study and write `earpiece.json` beside it."""
    out_path = study_dir / OUTPUT_NAME
    if out_path.exists():
        raise EarpieceError(f"{out_path} already exists; an earpiece record is never overwritten.")
    results = json.loads((study_dir / "results.json").read_text(encoding="utf-8"))
    selected = results.get("selected_candidate")
    if not selected or selected.get("kind") != "design":
        raise EarpieceError("The study selected no design, so there is nothing to build.")
    dials = dials if dials is not None else describe_dials()
    locked = locked_params(selected.get("parameters", {}), dials)
    studied = study_collector(selected.get("parameters", {}))
    study_id = results.get("study_id", study_dir.name)
    builds: list[dict[str, Any]] = []
    chosen: dict[str, Any] = {}

    @tool
    def build_earpiece(
        aim_yaw_deg: float,
        aim_pitch_deg: float,
        hood_mm: float,
        rim_conformity: float,
        mouth_stretch: float,
        flare_mid1: float,
        flare_mid2: float,
        canal_stem_mm: float,
        tab_side_deg: float,
        why: str,
        collector: dict[str, Any] | None = None,
    ) -> str:
        """Build one earpiece with these dials and an optional collector, and run its fit checks."""
        if len(builds) >= max_builds:
            return "The build budget is spent. Call finish with a design_id that built, or stop."
        shaping = {
            "aim_yaw_deg": aim_yaw_deg,
            "aim_pitch_deg": aim_pitch_deg,
            "hood_mm": hood_mm,
            "rim_conformity": rim_conformity,
            "mouth_stretch": mouth_stretch,
            "flare_mid1": flare_mid1,
            "flare_mid2": flare_mid2,
            "canal_stem_mm": canal_stem_mm,
            "tab_side_deg": tab_side_deg,
            # The model's direction and outline, at the study's reach and opening area.
            "collector": lock_collector(collector, studied),
        }
        if shaping["collector"] is not None:
            shaping["hood_mm"] = 0.0  # the builder takes a collector or a hood, never both
        design_id = f"{study_id}-e{len(builds) + 1}"
        # Locked numbers go in LAST so no shaping value can ever replace them.
        sent = {**shaping, **locked}
        report = build(patient_dir, sent, design_id)
        differs = departures(report.get("geometry") or {}, locked, studied) if report.get("ok") else []
        builds.append(
            {
                "design_id": design_id,
                "why": why,
                "shaping": {k: v for k, v in sent.items() if k not in ("throat_mm2", "mouth_mm2")},
                "report": report,
                "departures_from_study": differs,
            }
        )
        keep = ("ok", "reasons", "warnings", "checks", "geometry")
        return json.dumps(
            {
                "design_id": design_id,
                "applied_from_study": {**locked, "collector": sent["collector"]},
                "departures_from_study": differs,
                **{k: report[k] for k in keep if k in report},
            }
        )

    @tool
    def finish(design_id: str, explanation: str) -> str:
        """Choose the finished earpiece. Only a design_id whose build succeeded is accepted."""
        built = {b["design_id"]: b for b in builds if b["report"].get("ok")}
        if design_id not in built:
            return f"Rejected: {design_id} did not build. Builds that succeeded: {sorted(built) or 'none'}."
        chosen.update(design_id=design_id, explanation=explanation, chosen_by="agent")
        return "Done."

    tools = {t.name: t for t in (build_earpiece, finish)}
    bound = model.bind_tools(list(tools.values()))
    messages: list[BaseMessage] = [
        SystemMessage(SYSTEM),
        HumanMessage(brief(results, patient_dir, locked, dials)),
    ]
    for _ in range(2 * max_builds + 2):
        reply = bound.invoke(messages)
        messages.append(reply)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            break
        for call in calls:
            handler = tools.get(call["name"])
            n_before = len(builds)
            content = handler.invoke(call["args"]) if handler else f"Unknown tool {call['name']}."
            messages.append(
                ToolMessage(content=_with_preview(str(content), builds[n_before:]), tool_call_id=call["id"])
            )
        if chosen:
            break

    ok = [b for b in builds if b["report"].get("ok")]
    if not chosen and ok:
        # Code picks when the model did not: the successful build with the most wall around the bore.
        best = max(ok, key=lambda b: b["report"]["checks"]["bore_wall_mm"])
        chosen.update(design_id=best["design_id"], explanation="", chosen_by="code_fallback")
    sizes: dict[str, Any] = {}
    if chosen:
        # M is the chosen build; S and L are the SAME design with the cast shrunk or grown. They are
        # code's job, outside the model's build budget, and a size that fails is reported, not hidden.
        base = next(b for b in builds if b["design_id"] == chosen["design_id"])
        sizes["M"] = {"design_id": base["design_id"], "ok": True}
        for size, offset in (("S", -0.5), ("L", 0.5)):
            size_id = f"{base['design_id']}-{size}"
            report = build(patient_dir, {**base["shaping"], **locked, "fit_offset_mm": offset}, size_id)
            sizes[size] = {
                "design_id": size_id,
                "ok": bool(report.get("ok")),
                "reasons": report.get("reasons", []),
            }
    record = {
        "study_id": study_id,
        "patient_dir": str(patient_dir),
        "selected_parameters": selected.get("parameters", {}),
        "locked": locked,
        "study_collector": (None if studied is None else {"reach_mm": studied[0], "opening_mm2": studied[1]}),
        "builds": builds,
        "chosen": chosen or None,
        "departures_from_study": next(
            (b["departures_from_study"] for b in builds if chosen and b["design_id"] == chosen["design_id"]),
            [],
        ),
        "sizes": sizes,
        "status": "built" if chosen else "no_buildable_design",
    }
    out_path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record
