"""Rough head from one frontal selfie, with the patient's two reconstructed ears attached.

    python -m headrecon.head <selfie.jpg | -> <out_dir> [--ears <patient_dir>]

MediaPipe Face Landmarker (Apache-2.0, face_landmarker.task in WEIGHTS_DIR) finds 478 face landmarks.
Pixel measurements become mm through ONE anchor, an average interpupillary distance; head length is not
visible from the front and comes from population ratios. The mesh is a smooth implicit head (deformed
ellipsoid, flattened face, neck stub) scaled to those dims. No selfie, no face or a landmarker failure
gives the AVERAGE adult head instead — this stage NEVER fails the patient.

Head frame (head.json["frame"]): mm, origin midway between the two tragions, +x toward the person's
LEFT, +y up, +z forward. Ear frame: earrecon's ear.ply / ear.glb / ear_skin.glb and hornsim.wavesim's
ear.json / runs.json all share ONE frame (+x lateral, +y up, forward -z for a right ear, +z for a left
ear, which earrecon mirrors) — so mesh_to_head and waves_to_head are the SAME matrix today.

Writes <out_dir>/: landmarks.jpg (face found only), head.glb, head_ears.glb, head.json (last).
"""
import argparse
import json
import os

import numpy as np
import trimesh

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "face_landmarker.task"
FRAME = "head, mm: origin midway between the two tragions; +x toward the person's LEFT, +y up, +z forward (toward the nose)"
SKIN_GREY = [0.80, 0.76, 0.73, 1.0]

IPD_MM = 63.0               # average adult interpupillary distance (Dodgson 2004: mean 63.4 mm)
BIZYGOMATIC_PER_BREADTH = 0.91   # face width / head breadth, adult population ratio
CEPHALIC_INDEX = 0.79       # head breadth / head length, adult population mean
FOREHEAD_CHIN_PER_HEIGHT = 0.78  # landmark 10 (upper forehead) to chin, as a share of vertex to chin
TRAGION_BELOW_PUPILS_MM = 15.0   # tragion sits just below the Frankfort plane through the lower orbit
AVERAGE = {"breadth": 151.0, "length": 192.0, "height": 226.0, "tragion_above_chin": 108.0}
RANGES = {"breadth": (135.0, 170.0), "length": (170.0, 215.0), "height": (200.0, 255.0)}

# MediaPipe face-mesh indices: iris centres, upper forehead, chin, and the face oval (forehead round to the chin and back).
IRIS_R, IRIS_L, FOREHEAD, CHIN = 468, 473, 10, 152
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
             148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
# The lower face's width relative to ear level, sampled from the ear (t = 0) down to the chin (t = -1, t = y / tragion_above_chin).
JAW_T = np.linspace(-1.0, 0.0, 11)
# Average adult jaw taper at JAW_T and chin depth, for a head with no face to measure.
AVERAGE_JAW = {"r": [0.30, 0.48, 0.62, 0.72, 0.80, 0.86, 0.91, 0.95, 0.98, 0.995, 1.0], "chin_forward": -5.0}
# Chin ahead of (+) or behind (-) the forehead. Capped at 0: a selfie from BELOW (the usual phone angle) makes
# the chin read nearer the camera than it is, and an uncapped value juts the jaw forward.
CHIN_FORWARD_MM = (-25.0, 0.0)


def weights_dir():
    return os.environ.get("WEIGHTS_DIR", os.path.join(BACKEND, "weights"))


# ---------------------------------------------------------------- selfie -> dims

def face_landmarks(rgb):
    """(478, 3) landmarks of the most prominent face — x, y in pixels, z (depth, + away from the camera) in the
    SAME pixel scale as x — or None when no face is found.
    Raises when mediapipe or its model is missing — the caller falls back to the average head."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    model = os.path.join(weights_dir(), MODEL)
    if not os.path.isfile(model):
        raise FileNotFoundError(f"{MODEL} is not in WEIGHTS_DIR ({weights_dir()}); run scripts/fetch_weights.sh")
    opts = vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=model), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as fl:
        res = fl.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not res.face_landmarks:
        return None
    h, w = rgb.shape[:2]
    return np.array([[p.x * w, p.y * h, p.z * w] for p in res.face_landmarks[0]])


def measure(lm):
    """Face measurements in mm from frontal landmarks. Taken along the eye line, so a tilted (rolled)
    head does not stretch the width; a turned (yawed) head shrinks the IPD and the widths together."""
    z = lm[:, 2] if lm.shape[1] > 2 else np.zeros(len(lm))
    lm = lm[:, :2]
    eye_r, eye_l = lm[IRIS_R], lm[IRIS_L]
    ipd_px = float(np.linalg.norm(eye_l - eye_r))
    across = (eye_l - eye_r) / ipd_px
    down = np.array([-across[1], across[0]])
    if down[1] < 0:
        down = -down
    mm = IPD_MM / ipd_px
    u, v = (lm - (eye_r + eye_l) / 2) @ across, (lm - (eye_r + eye_l) / 2) @ down
    return {"ipd_px": ipd_px, "mm_per_px": mm,
            "face_width_mm": float(np.ptp(u)) * mm,                        # face-oval extremes, cheek level
            "forehead_chin_mm": float(v[CHIN] - v[FOREHEAD]) * mm,
            "pupils_above_chin_mm": float(v[CHIN]) * mm,
            # MediaPipe depth: smaller z is nearer the camera, so forehead minus chin is how far the chin juts forward.
            "chin_forward_mm": float(z[FOREHEAD] - z[CHIN]) * mm}


def jaw_profile(lm, meas, tragion_above_chin):
    """The face oval's half-width at each JAW_T level, relative to its half-width at ear level. Read off the
    photo's outline, so the jaw is the person's OWN shape — a fixed taper drew every jaw the same."""
    lm2 = lm[:, :2]
    eye_r, eye_l = lm2[IRIS_R], lm2[IRIS_L]
    across = (eye_l - eye_r) / np.linalg.norm(eye_l - eye_r)
    down = np.array([-across[1], across[0]])
    if down[1] < 0:
        down = -down
    oval = (lm2[FACE_OVAL] - (eye_r + eye_l) / 2) * meas["mm_per_px"]
    u, v = oval @ across, oval @ down
    def side(sel):                                  # u as a function of v down one side of the oval
        o = np.argsort(v[sel])
        return v[sel][o], u[sel][o]
    vl, ul = side(u > 0)
    vr, ur = side(u < 0)
    v_at = (meas["pupils_above_chin_mm"] - tragion_above_chin) - JAW_T * tragion_above_chin
    hw = (np.interp(v_at, vl, ul) - np.interp(v_at, vr, ur)) / 2
    r = np.clip(hw / max(hw[-1], 1e-6), 0.15, 1.0)
    return [float(x) for x in np.maximum.accumulate(r)]   # never wider below than above


def dims_from(meas):
    """Head breadth / length / height (mm) plus tragion height above the chin, clamped to adult ranges."""
    raw = {"breadth": meas["face_width_mm"] / BIZYGOMATIC_PER_BREADTH,
           "height": meas["forehead_chin_mm"] / FOREHEAD_CHIN_PER_HEIGHT}
    raw["length"] = raw["breadth"] / CEPHALIC_INDEX
    d = {k: float(np.clip(raw[k], *RANGES[k])) for k in RANGES}
    t = meas["pupils_above_chin_mm"] - TRAGION_BELOW_PUPILS_MM
    d["tragion_above_chin"] = float(np.clip(t, 0.40 * d["height"], 0.55 * d["height"]))
    return d, [k for k in RANGES if raw[k] != d[k]]


# ---------------------------------------------------------------- implicit head

def _geometry(d, jaw=None):
    """`jaw` is {"r": width ratios at JAW_T, "chin_forward": mm} from the selfie, or None for the average jaw."""
    B, L, H, T = d["breadth"], d["length"], d["height"], d["tragion_above_chin"]
    jaw = jaw or AVERAGE_JAW
    yc = 0.13 * T                       # widest level sits above the ears, as on a real skull
    # Width ratio as an EVEN polynomial in t = y / T, fitted over the samples and their mirror: r'(0) = 0, so the
    # jaw joins the skull at ear level without a crease (the field must stay C1 for the Newton projection).
    t = np.concatenate([JAW_T, -JAW_T])
    rr = np.concatenate([jaw["r"], jaw["r"]])
    # No constant term in the fit: r(0) = 1 EXACTLY, so ear level stays at the full head breadth.
    jaw_c = [1.0, *np.linalg.lstsq(np.stack([t ** k for k in (2, 4, 6)], 1), rr - 1.0, rcond=None)[0]]
    fwd = float(np.clip(jaw["chin_forward"], *CHIN_FORWARD_MM))
    k = 0.3                             # the face's front-back depth shrinks this much toward the chin
    return {"a": B / 2, "b_up": H - T - yc, "b_down": T + yc, "yc": yc, "T": T,
            "zc": 0.03 * L,             # the tragion is slightly BEHIND the head's front-back midpoint
            "c": L / 2, "k": k,
            # The lower head's centre moves forward so its front lands at the forehead's front plus the measured
            # chin offset; the 0.13 × L makes up for the ellipsoid rounding the chin back (without it, a chin level
            # with the forehead drew ~30 mm receded). A fixed 0.4 × L shear put every chin ~8 cm AHEAD of the face.
            "shift": fwd + k * L / 2 + 0.13 * L, "jaw": [float(x) for x in jaw_c], "R": (B + L + H) / 6,
            "neck_r": 0.30 * B, "neck_z": 0.03 * L - 0.12 * L, "neck_top": -0.35 * T, "neck_bot": -T - 40.0}  # neck NARROWER than the jaw, or from the front it hides the jaw


def jaw_ratio(y, g):
    t = np.clip(y / g["T"], -1.0, 0.0)
    c0, c2, c4, c6 = g["jaw"]
    return np.clip(c0 + c2 * t ** 2 + c4 * t ** 4 + c6 * t ** 6, 0.15, 1.0)


def field(P, g):
    """Signed field, negative inside, ~mm near the surface. Smooth (C1) everywhere: Newton projection
    onto f = 0 and the tragion normal both rely on that."""
    x, y, z = np.asarray(P, float).T
    yy = y - g["yc"]
    s = np.clip(-yy / g["b_down"], 0, 1) ** 1.5       # 0 above the widest level, 1 at the chin
    zz = z - g["zc"] - g["shift"] * s ** (4 / 3)
    a = g["a"] * np.where(y < 0, jaw_ratio(y, g), 1.0)   # the person's own jaw taper below the ears
    b = np.where(yy >= 0, g["b_up"], g["b_down"])
    c = np.where(zz >= 0, g["c"] * (1 - g["k"] * s), g["c"] * (1 - 0.35 * s))
    p = np.where(zz >= 0, 2.6, 2.0)                       # flatter face than back of head
    q = (x / a) ** 2 + (yy / b) ** 2 + np.abs(zz / c) ** p
    head = (np.sqrt(q) - 1) * g["R"]

    dr = np.hypot(x, z - g["neck_z"]) - g["neck_r"]
    dy = np.maximum(g["neck_bot"] - y, y - g["neck_top"])
    neck = np.hypot(np.maximum(dr, 0), np.maximum(dy, 0)) + np.minimum(np.maximum(dr, dy), 0)
    k = 20.0                                              # smooth union: the neck blends into the jaw
    h = np.clip(0.5 + 0.5 * (neck - head) / k, 0, 1)
    return neck * (1 - h) + head * h - k * h * (1 - h)


def gradient(P, g, eps=0.05):
    P = np.atleast_2d(P).astype(float)
    return np.stack([(field(P + e, g) - field(P - e, g)) / (2 * eps) for e in np.eye(3) * eps], 1)


def project(P, g, iters=6):
    for _ in range(iters):
        gr = gradient(P, g)
        P = P - (field(P, g) / np.maximum((gr ** 2).sum(1), 1e-9))[:, None] * gr
    return P


def tragion(g):
    """Surface point straight out to the LEFT (+x) at ear level (y = z = 0) and its outward normal.
    The head is mirror-symmetric in x, so the right tragion is (-x, 0, 0) — which is what puts the
    origin midway between them."""
    lo, hi = 0.0, 2 * g["a"]
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if field([[mid, 0, 0]], g)[0] < 0 else (lo, mid)
    p = np.array([(lo + hi) / 2, 0.0, 0.0])
    n = gradient(p, g)[0]
    return p, n / np.linalg.norm(n)


def head_mesh(g, cell=None):
    """Closed surface by marching cubes on the field, vertices then projected exactly onto f = 0.
    The cell grows with the head so every size lands near 9k faces."""
    from skimage import measure as skm
    cell = cell or 6.8 * (g["a"] * g["c"] * (g["b_up"] + g["b_down"]) / (75.5 * 96 * 226)) ** (1 / 3)
    lo = np.array([-g["a"] - 15, g["neck_bot"] - 10, g["zc"] - g["c"] - 15])
    hi = np.array([g["a"] + 15, g["yc"] + g["b_up"] + 15, g["zc"] + max(g["shift"], 0) + g["c"] + 15])
    axes = [np.arange(lo[i], hi[i] + cell, cell) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), -1)
    vol = field(grid.reshape(-1, 3), g).reshape(grid.shape[:3])
    vol = np.pad(vol, 1, constant_values=vol.max())         # closed even if the box clips
    v, f, _, _ = skm.marching_cubes(vol, 0.0, spacing=(cell,) * 3)
    v = v - cell + lo
    # process=False: merging the projected vertices pinches near-coincident ones together and the
    # surface is NO LONGER closed (142 pieces at a 5 mm cell); marching_cubes already shares vertices.
    m = trimesh.Trimesh(project(v, g), f, process=False)
    m.fix_normals()
    return m


# ---------------------------------------------------------------- ears

def ear_frame(side):
    """Ear-frame (lateral, up, forward) unit axes as columns. earrecon mirrors z for a LEFT ear, so
    forward is +z there and -z for a right ear — wavesim.load_ear's `front` says the same."""
    return np.array([[1.0, 0, 0], [0, 1, 0], [0, 0, 1.0 if side == "left" else -1.0]]).T


def ear_to_head(side, canal, trag, normal):
    """4x4 placing the ear so its canal opening sits ON the tragion, its lateral axis along the head's
    outward normal and its up as close to +y as the normal allows. The ear frame's flat head plane
    (x = canal x) becomes the head's tangent plane at the tragion — so the convex head stays behind it."""
    n = np.asarray(normal, float) / np.linalg.norm(normal)
    up = np.array([0.0, 1, 0]) - n[1] * n
    up /= np.linalg.norm(up)
    fwd = np.array([0.0, 0, 1]) - n[2] * n - up[2] * up
    fwd /= np.linalg.norm(fwd)
    R = np.stack([n, up, fwd], 1) @ np.linalg.inv(ear_frame(side))
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = np.asarray(trag, float) - R @ np.asarray(canal, float)
    return M


def canal_point(ear_dir, side, landmarks_xlsx=None):
    """Canal opening in the ear frame: the wave sim's own ear.json when it exists, otherwise the SAME
    computation (wavesim.load_ear) — the head stage runs before the wave sim in a new patient's job."""
    ej = os.path.join(ear_dir, "waves", "ear.json")
    if os.path.isfile(ej):
        try:
            return np.array(json.load(open(ej))["canal"]["point"], float)
        except (ValueError, KeyError, TypeError):
            pass                                   # a stub or half-written file: recompute
    from hornsim import wavesim
    from hornsim.context import load_defaults
    cfg = load_defaults()
    cfg["ear_world"]["landmarks_xlsx"] = landmarks_xlsx or os.environ.get(
        "LANDMARKS_XLSX", os.path.join(BACKEND, "third_party", "AudioEar", "data", "55_landmarks.xlsx"))
    _, world, _ = wavesim.load_ear(os.path.join(ear_dir, "ear", "ear.ply"), side == "left", cfg)
    return world.canal_point


def ear_display_mesh(ear_dir):
    for name in ("ear_skin.glb", "ear.glb"):
        p = os.path.join(ear_dir, "ear", name)
        if os.path.isfile(p):
            return trimesh.load(p, force="mesh", process=False)
    return None


# ---------------------------------------------------------------- outputs

def _read_rgb(path):
    from PIL import Image, ImageOps
    return np.asarray(ImageOps.exif_transpose(Image.open(path)).convert("RGB"))


def save_landmarks(rgb, lm, path):
    """Every landmark as a small dot; the six points the measurements use in orange."""
    from PIL import Image, ImageDraw
    img = Image.fromarray(rgb)
    scale = min(1.0, 1600 / max(img.size))
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)))
    dr = ImageDraw.Draw(img)
    r = max(1.0, max(img.size) / 600)
    key = {IRIS_R, IRIS_L, FOREHEAD, CHIN, int(np.argmin(lm[:, 0])), int(np.argmax(lm[:, 0]))}
    for i, (x, y) in enumerate(lm[:, :2] * scale):
        rr, col = (2.5 * r, (255, 140, 0)) if i in key else (r, (80, 220, 255))
        dr.ellipse([x - rr, y - rr, x + rr, y + rr], fill=col)
    img.save(path, quality=90)


def build(out, selfie=None, ears=None, landmarks_xlsx=None, log=print):
    """Head stage. `ears` maps "left"/"right" to the folder holding that ear's ear/ (and waves/).
    Returns {"source", "dims_mm", "note"?} for job.json; head.json is written LAST."""
    os.makedirs(out, exist_ok=True)
    notes, source = [], "average"
    dims, jaw = dict(AVERAGE), None
    lm_path = os.path.join(out, "landmarks.jpg")
    if not selfie or not os.path.isfile(selfie):
        notes.append("No selfie was given, so this is the average adult head.")
    else:
        try:
            rgb = _read_rgb(selfie)
            lm = face_landmarks(rgb)
            if lm is None:
                notes.append("No face was found in the selfie, so this is the average adult head.")
            else:
                meas = measure(lm)
                dims, clamped = dims_from(meas)
                jaw = {"r": jaw_profile(lm, meas, dims["tragion_above_chin"]), "chin_forward": meas["chin_forward_mm"]}
                source = "selfie"
                save_landmarks(rgb, lm, lm_path)
                log("head: face " + ", ".join(f"{k} {v:.1f}" for k, v in meas.items()))
                log("head: jaw width / ear-level width, ear to chin: " + " ".join(f"{x:.2f}" for x in jaw["r"][::-1]))
                if clamped:
                    notes.append("Clamped to the adult range: " + ", ".join(clamped) + ".")
        except Exception as e:  # mediapipe missing or broken must NOT cost the patient a head
            notes.append(f"The face landmarker failed ({type(e).__name__}: {e}), so this is the average adult head.")
    if source != "selfie" and os.path.exists(lm_path):
        os.remove(lm_path)                               # a stale overlay from an earlier selfie
    log(f"head: {source}, breadth {dims['breadth']:.0f}, length {dims['length']:.0f}, height {dims['height']:.0f} mm")

    g = _geometry(dims, jaw)
    head = head_mesh(g)
    head.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=SKIN_GREY, metallicFactor=0.0, roughnessFactor=0.8))
    head.export(os.path.join(out, "head.glb"))

    t_left, n_left = tragion(g)
    mirror = np.array([-1.0, 1, 1])
    placed, scene = {}, [head]
    for side, ed in (ears or {}).items():
        trag, n = (t_left, n_left) if side == "left" else (t_left * mirror, n_left * mirror)
        try:
            M = ear_to_head(side, canal_point(ed, side, landmarks_xlsx), trag, n)
            m = ear_display_mesh(ed)
            if m is not None:
                scene.append(m.copy().apply_transform(M))
        except Exception as e:  # one bad ear leaves the head and the other ear in place
            notes.append(f"The {side} ear could not be attached ({type(e).__name__}: {e}).")
            continue
        flat = [round(float(v), 6) for v in M.ravel()]
        placed[side] = {"tragion": np.round(trag, 3).tolist(), "normal": np.round(n, 6).tolist(),
                        "mesh_to_head": flat, "waves_to_head": flat}
    trimesh.Scene(scene).export(os.path.join(out, "head_ears.glb"))

    dims_mm = {k: round(dims[k], 1) for k in ("breadth", "length", "height")}
    assumptions = [
        f"Scale comes from ONE assumption: an average adult interpupillary distance of {IPD_MM:.0f} mm."
        if source == "selfie" else "Average adult head dimensions; nothing was measured.",
        f"Head breadth = face width (face-oval extremes) / {BIZYGOMATIC_PER_BREADTH}; head length = breadth / "
        f"{CEPHALIC_INDEX} (mean cephalic index) — a frontal photo cannot see head length.",
        f"Head height (vertex to chin) = forehead-to-chin / {FOREHEAD_CHIN_PER_HEIGHT}; the top of the head is hidden by hair.",
        f"Tragions sit {TRAGION_BELOW_PUPILS_MM:.0f} mm below the pupil line, on the side of the head, slightly behind its "
        "front-back midpoint; the photo cannot see them.",
        "The head is a smooth rough shape (deformed ellipsoid, flattened face, neck stub), not a scan. Below the ears its "
        "width follows the photo's face outline and the chin sits where the landmarks' depth puts it"
        + ("." if source == "selfie" else " for an average face."),
        "Each ear's canal opening is placed on its tragion with the ear's flat back plane tangent to the head there.",
    ]
    info = {"frame": FRAME, "source": source, "dims_mm": dims_mm, "assumptions": assumptions, "ears": placed}
    if notes:
        info["note"] = " ".join(notes)
    with open(os.path.join(out, "head.json.tmp"), "w") as f:
        json.dump(info, f, indent=1)
    os.replace(os.path.join(out, "head.json.tmp"), os.path.join(out, "head.json"))
    return {"source": source, "dims_mm": dims_mm, **({"note": info["note"]} if notes else {})}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("selfie", help="frontal selfie, or - for the average head")
    ap.add_argument("out")
    ap.add_argument("--ears", help="patient folder holding left/ and right/ (each with ear/ and maybe waves/)")
    a = ap.parse_args()
    ears = {s: os.path.join(a.ears, s) for s in ("left", "right")
            if a.ears and os.path.isfile(os.path.join(a.ears, s, "ear", "ear.ply"))}
    print(json.dumps(build(a.out, None if a.selfie == "-" else a.selfie, ears), indent=1))
