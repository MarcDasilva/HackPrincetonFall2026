"""The patient's head shape for the dummy-head wave grid (hornsim.head_grid), from one front photo.

    python -m hornsim.head_shape landmarks.json      # prints the fitted profile

The browser runs MediaPipe's face landmarker on the photo (frontend app/sim/lib/faceShape.ts), so the
photo itself never leaves the device; only the 478 normalised landmarks come here. What a front photo
measures, and what is assumed:

  measured   scale (iris diameter, below), the roll of the face, the face's outline from chin to
             forehead (MediaPipe's face-oval contour follows skin, so hair is ignored), and so the
             width of the lower head (cheeks, jaw, chin) at each height, the head breadth at the
             cheekbones, the eye line and the ear-canal height.
  with the hair outline (optional, MediaPipe multiclass segmentation run in the browser):
             the crown is capped under the top of the hair, the breadth is the outline's width at
             the temples less the hair at the sides, and the vault's roundness is fitted.
  assumed    everything a front view cannot see: front-to-back depth (head length / breadth from the
             adult mean, ITU-T P.58: 194 / 152), the crown hidden by hair (vertex as far above the eye
             line as the chin is below it, the classical facial proportion, capped by the hair), skull
             breadth above the cheekbones (euryon / bizygomatic breadth ~1.09 from adult means) when
             there is no hair outline, hair thickness, and the canal a little in front of mid-length.

Scale: the horizontal visible iris diameter is 11.7 mm with a small spread in adults (Rüfer, Schröder
& Erb 2005, Cornea 24:259, 11.71 ± 0.42 mm), so it sets mm per pixel with ~4 % error.
Ear-canal height: the Frankfort horizontal runs through the tragion and the orbitale (lowest point
of the eye socket rim), so the canal sits at orbitale height, taken as ORBITALE_BELOW_LID_MM under
the lower eyelid margin.

Head frame as in hornsim.head_grid: mm, +x toward the right ear, +y up, -z forward, y = 0 at the
canal height. A profile is horizontal ellipse sections stacked in y: half-width w(y), half-depth d(y),
centre z c(y). The fit is deliberately one smooth oval (no face): breadth, chin-to-crown height and
the jaw's taper come from the photo. The neck and shoulders keep the generic shape.
"""
import json
import math
import sys

import numpy as np

IRIS_MM = 11.7
ORBITALE_BELOW_LID_MM = 6.0      # ASSUMPTION: bony orbit rim below the lower lid margin
LENGTH_PER_BREADTH = 194.0 / 152.0
EURYON_PER_BIZYGOMATIC = 1.09
CANAL_FORWARD_MM = 6.0           # canal opening this far in front of the head's mid-length (ASSUMPTION)
DY = 2.0
# Top of the head. Front view of the vault: a superellipse, not an ellipse; skull outlines are fuller
# at the temples and flatter on top than an ellipse of the same height (an ellipse reads as a dome).
# ASSUMED when the photo's hair outline cannot say: N_TOP_DEFAULT; fitted otherwise within N_TOP_RANGE.
N_TOP_DEFAULT = 2.5
N_TOP_RANGE = (2.0, 3.4)
HAIR_TOP_MM = 10.0      # ASSUMPTION: scalp at least this far under the top of the hair outline
HAIR_SIDE_MM = 6.0      # ASSUMPTION: hair thickness at the sides of the head, above the ears
SIL_BREADTH_RANGE = (1.0, 1.25)   # silhouette breadth accepted between these multiples of the cheekbone width
# Below the eyes. Adult anthropometric means: head breadth across the tragions ~0.93 of the maximum
# (euryon) breadth; from about 25 mm below the canal down, the face outline is the head's outline.
BITRAGION_PER_EURYON = 0.93
JAW_FROM_MM = 25.0
WIDEST_FRAC = 0.3       # ASSUMPTION: the head is widest (euryon, over the parietal bones) this far from the eye line to the crown

# MediaPipe face mesh indices (canonical face model; the landmarker returns 478 = 468 + 10 iris)
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
FOREHEAD, CHIN = 10, 152
MIDLINE = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 2, 164, 0, 17, 18, 200, 199, 175, 152]
IRIS = {"a": (468, [469, 470, 471, 472]), "b": (473, [474, 475, 476, 477])}
LOWER_LID = [145, 374]

NECK = {"center_xz": [0.0, 18.0], "axes_xz": [52.0, 50.0], "y": [-175.0, -45.0]}
TORSO = {"center": [0.0, -255.0, 18.0], "axes": [225.0, 100.0, 118.0]}


class HeadShape:
    """Stacked horizontal ellipses (y ascending) + neck + shoulders, in the head frame."""

    def __init__(self, y, w, d, c, source, neck=None, torso=None, meta=None):
        self.y, self.w, self.d, self.c = (np.asarray(v, float) for v in (y, w, d, c))
        self.source = source
        self.neck = neck or json.loads(json.dumps(NECK))
        self.torso = torso or json.loads(json.dumps(TORSO))
        self.meta = meta or {}

    # ---------------------------------------------------------------- geometry
    def _at(self, y):
        y = np.asarray(y, float)
        return (np.interp(y, self.y, self.w), np.interp(y, self.y, self.d), np.interp(y, self.y, self.c),
                (y >= self.y[0]) & (y <= self.y[-1]))

    def head_solid(self, P):
        """P (..., 3) -> True inside the head, neck or shoulders."""
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        w, d, c, inside_y = self._at(y)
        head = inside_y & ((x / np.maximum(w, 1e-6)) ** 2 + ((z - c) / np.maximum(d, 1e-6)) ** 2 <= 1)
        n = self.neck
        neck = ((((x - n["center_xz"][0]) / n["axes_xz"][0]) ** 2 + ((z - n["center_xz"][1]) / n["axes_xz"][1]) ** 2 <= 1)
                & (y >= n["y"][0]) & (y <= n["y"][1]))
        t = self.torso
        torso = (((P - np.array(t["center"])) / np.array(t["axes"])) ** 2).sum(-1) <= 1
        return head | neck | torso

    def surface_x(self, y, z):
        """|x| of the head surface at (y, z); 0 where the head does not reach."""
        w, d, c, inside_y = self._at(y)
        r = 1 - ((np.asarray(z, float) - c) / np.maximum(d, 1e-6)) ** 2
        return np.where(inside_y, w * np.sqrt(np.clip(r, 0, None)), 0.0)

    def canal_anchor_x(self):
        return float(self.surface_x(0.0, 0.0))

    def extent(self):
        """(max |x|, z min, z max, y max) of the head part."""
        return float(self.w.max()), float((self.c - self.d).min()), float((self.c + self.d).max()), float(self.y[-1])

    def to_json(self):
        return {"source": self.source, "profile": {"y": self.y.round(2).tolist(), "w": self.w.round(2).tolist(),
                                                   "d": self.d.round(2).tolist(), "c": self.c.round(2).tolist()},
                "neck": self.neck, "torso": self.torso, "meta": self.meta}

    @classmethod
    def from_json(cls, j):
        p = j["profile"]
        return cls(p["y"], p["w"], p["d"], p["c"], j.get("source", "?"), j.get("neck"), j.get("torso"), j.get("meta"))


def average():
    """The generic head: breadth 152 mm, length ~194 mm (ITU-T P.58 adult mean), one ellipsoid."""
    cy, a, cz = 15.0, (76.0, 108.0, 97.0), 6.0
    y = np.arange(cy - a[1], cy + a[1] + 1e-9, DY)
    y[0], y[-1] = cy - a[1] + 0.5, cy + a[1] - 0.5
    s = np.sqrt(np.clip(1 - ((y - cy) / a[1]) ** 2, 0, None))
    return HeadShape(y, a[0] * s, a[2] * s, np.full_like(y, cz), "average head (ITU-T P.58 breadth and length)",
                     meta={"breadth_mm": 152.0, "length_mm": 194.0, "measured": False})


# ---------------------------------------------------------------- fit from a front photo

def _oval_halfwidth(pts, ys):
    """Half the width of the closed polygon `pts` (N, 2: x, y up) on each horizontal line in `ys`."""
    out = np.full(len(ys), np.nan)
    a, b = pts, np.roll(pts, -1, 0)
    for k, yy in enumerate(ys):
        lo, hi = np.minimum(a[:, 1], b[:, 1]), np.maximum(a[:, 1], b[:, 1])
        hit = (yy >= lo) & (yy < hi) & (hi > lo)
        if hit.sum() < 2:
            continue
        t = (yy - a[hit, 1]) / (b[hit, 1] - a[hit, 1])
        xs = a[hit, 0] + t * (b[hit, 0] - a[hit, 0])
        out[k] = (xs.max() - xs.min()) / 2
    return out


def oval_profile(ys, face_w, y_eye, y_chin, breadth, crown, n_top=N_TOP_DEFAULT, length=None):
    """The head's profile from the measured face outline (half-widths face_w at heights ys, mm, canal at
    0) and the fitted sizes. Returns y, w, d, c and the jaw exponent. n_top: the vault's superellipse
    exponent (2 = ellipse; larger = fuller temples, flatter top). length: head length (front-back),
    default breadth × LENGTH_PER_BREADTH."""
    # One smooth oval, no facial detail. Front view: widest (breadth B) above the ears at widest_y; above
    # that a superellipse quadrant up to the crown; below it a half-superellipse down to the chin,
    # w = B/2 (1 - t^n)^(1/n), whose exponent is fitted to ABSOLUTE widths: the head across the ears
    # (BITRAGION_PER_EURYON × B at the canal height) and the photo's jawline where the face outline is
    # the head's outline (JAW_FROM_MM below the canal and lower). So the head narrows below the eyes the
    # way a head does, instead of keeping the skull's breadth down to the cheeks.
    # Plan view: every section is an ellipse with the same length/breadth ratio about the same centre,
    # so the side view is the same oval stretched to the head's length (no flat face, no jutting jaw).
    y_wide = widest_y(y_eye, crown)

    def lower_w(y, n):
        t = np.clip((y_wide - y) / (y_wide - y_chin), 0, 1)
        return breadth / 2 * (1 - t ** n) ** (1 / n)

    ty, tw = [0.0], [BITRAGION_PER_EURYON * breadth / 2]          # across the ears, at the canal height
    jaw = (ys <= -JAW_FROM_MM) & (ys > y_chin + 4)
    ty += ys[jaw].tolist()
    tw += face_w[jaw].tolist()
    ty, tw = np.array(ty), np.array(tw)
    if len(ty) >= 3:
        ns = np.linspace(1.2, 4.0, 57)
        wts = np.r_[3.0, np.ones(len(ty) - 1)]                       # the ear-level anchor counts for a few jaw rows
        err = [np.sum(wts * (lower_w(ty, n) - tw) ** 2) for n in ns]
        n_jaw = float(ns[int(np.argmin(err))])
    else:
        n_jaw = 2.0

    y = np.arange(math.ceil(y_chin / DY) * DY, crown, DY)
    y = np.append(y, crown - 0.5)
    upper = vault_w(y, y_wide, crown, breadth, n_top)
    w = np.where(y >= y_wide, upper, lower_w(y, n_jaw))
    w = np.maximum(w, 3.0)
    d = w * ((length or breadth * LENGTH_PER_BREADTH) / breadth)
    c = np.full_like(y, CANAL_FORWARD_MM)
    return y, w, d, c, n_jaw


def widest_y(y_eye, crown):
    """Height of the head's widest point: above the ears, WIDEST_FRAC of the way from the eye line to the crown."""
    return y_eye + WIDEST_FRAC * (crown - y_eye)


def vault_w(y, y_wide, crown, breadth, n):
    """Half-width of the head above its widest point: a superellipse quadrant from (B/2, y_wide) to (0, crown)."""
    t = np.clip((np.asarray(y, float) - y_wide) / (crown - y_wide), 0, 1)
    return breadth / 2 * (1 - t ** n) ** (1 / n)


def fit(landmarks, image_w, image_h, yaw_deg=None, head_rows=None):
    """478 MediaPipe landmarks (normalised x, y[, z]) of one front photo -> (HeadShape, report).

    head_rows: optional [[y, x_left, x_right], ...] in image pixels, the extent of the head's silhouette
    (hair + face skin, from MediaPipe's multiclass selfie segmenter) on each sampled row. With it the
    crown is capped under the top of the hair, the breadth is measured at the temples (less the hair
    at the sides), and the vault's roundness is fitted; without it those three are assumed."""
    L = np.asarray(landmarks, float)
    if L.ndim != 2 or L.shape[0] < 478 or L.shape[1] < 2:
        raise ValueError("need the 478 face-landmarker points (468 face + 10 iris)")
    px = np.stack([L[:, 0] * image_w, L[:, 1] * image_h], 1)
    warnings = []
    if yaw_deg is not None and abs(yaw_deg) > 12:
        warnings.append(f"face turned {yaw_deg:.0f}° from the camera: widths are foreshortened; retake facing the camera")

    # level the eyes (roll), then image y down -> y up
    ca, cb = px[IRIS["a"][0]], px[IRIS["b"][0]]
    roll = math.atan2(cb[1] - ca[1], cb[0] - ca[0])
    if abs(roll) > math.pi / 2:
        roll -= math.copysign(math.pi, roll)
    mid = (ca + cb) / 2
    R = np.array([[math.cos(-roll), -math.sin(-roll)], [math.sin(-roll), math.cos(-roll)]])
    q = (px - mid) @ R.T
    q[:, 1] *= -1

    iris_px = np.mean([np.mean([np.linalg.norm(q[r[0]] - q[r[2]]), np.linalg.norm(q[r[1]] - q[r[3]])])
                       for _, r in IRIS.values()])
    if iris_px < 4:
        raise ValueError("the irises are too small in this photo to set the scale; move closer")
    mm = IRIS_MM / iris_px
    q = q * mm
    ipd = float(np.linalg.norm(q[IRIS["a"][0]] - q[IRIS["b"][0]]))
    if not 50 <= ipd <= 78:
        warnings.append(f"eye spacing came out {ipd:.0f} mm (adults ~54-74): the iris scale may be off")

    x_mid = float(np.median(q[MIDLINE, 0]))
    q[:, 0] -= x_mid
    y_canal = float(np.mean(q[LOWER_LID, 1])) - ORBITALE_BELOW_LID_MM
    q[:, 1] -= y_canal                                  # y = 0 at the canal height
    y_eye = float((q[IRIS["a"][0], 1] + q[IRIS["b"][0], 1]) / 2)
    y_chin, y_brow = float(q[CHIN, 1]), float(q[FOREHEAD, 1])
    oval = q[FACE_OVAL]

    ys = np.arange(math.ceil(y_chin / DY) * DY, y_brow, DY)
    face_w = _oval_halfwidth(oval, ys)
    ok = ~np.isnan(face_w)
    ys, face_w = ys[ok], face_w[ok]
    bizyg = float(2 * face_w.max())
    breadth = EURYON_PER_BIZYGOMATIC * bizyg
    crown_prior = y_eye + (y_eye - y_chin)
    crown, n_top = crown_prior, N_TOP_DEFAULT
    sources = {"breadth": f"cheekbones × {EURYON_PER_BIZYGOMATIC}", "crown": "proportion (eye line to crown = chin to eye line)",
               "vault": f"assumed n = {N_TOP_DEFAULT}"}
    sil_poly = None

    if head_rows is not None and len(head_rows) >= 10:
        hr = np.asarray(head_rows, float)
        pts = np.vstack([hr[:, [1, 0]], hr[::-1][:, [2, 0]]])          # left edge down, right edge back up
        sp = (pts - mid) @ R.T
        sp[:, 1] *= -1
        sp = sp * mm
        sp[:, 0] -= x_mid
        sp[:, 1] -= y_canal
        sil_poly = sp
        hair_top = float(sp[:, 1].max())
        if hair_top > y_eye + 40:                                      # the silhouette reaches well above the eyes
            # crown: the proportion's estimate, but never above the scalp under the hair, and never below
            # 80 % of it (a hairline mistaken for the head's top would flatten the skull)
            crown = float(np.clip(crown_prior, y_eye + 0.8 * (y_eye - y_chin), hair_top - HAIR_TOP_MM))
            sources["crown"] = ("proportion, under the hair outline" if crown == crown_prior
                                else "under the top of the hair outline" if crown < crown_prior else "proportion (lower bound)")
            # breadth: widest silhouette between the eye line and a third of the way to the crown, less hair
            band = np.arange(y_eye, y_eye + 0.35 * (crown - y_eye), DY)
            sw = _oval_halfwidth(sp, band)
            if np.isfinite(sw).any():
                b_sil = 2 * (np.nanmax(sw) - HAIR_SIDE_MM)
                lo, hi = SIL_BREADTH_RANGE
                if lo * bizyg <= b_sil <= hi * bizyg:
                    breadth = b_sil
                    sources["breadth"] = f"temple width of the hair outline less {HAIR_SIDE_MM:.0f} mm hair each side"
                else:
                    warnings.append(f"hair outline breadth {b_sil:.0f} mm is implausible next to the face ({bizyg:.0f} mm): kept the face estimate")
            # vault roundness: the shape (not size) of the silhouette's upper outline, hair taken off the sides
            y_wide = widest_y(y_eye, crown)
            up = np.arange(y_wide, crown, DY)
            sw = _oval_halfwidth(sp, up) - HAIR_SIDE_MM
            okw = np.isfinite(sw) & (sw > 0)
            if okw.sum() >= 8:
                meas = sw[okw] / np.nanmax(sw[okw])
                ns = np.linspace(*N_TOP_RANGE, 29)
                err = [np.sum((vault_w(up[okw], y_wide, crown, 2.0, n) - meas) ** 2) for n in ns]
                n_top = float(ns[int(np.argmin(err))])
                sources["vault"] = f"fitted to the hair outline, n = {n_top:.2f}"

    # length from the face-based breadth, so hair that widens the measured breadth cannot stretch the head
    length = LENGTH_PER_BREADTH * EURYON_PER_BIZYGOMATIC * bizyg
    sources["length"] = f"cheekbones × {EURYON_PER_BIZYGOMATIC} × adult length/breadth {LENGTH_PER_BREADTH:.2f}"
    y, w, d, c, n_jaw = oval_profile(ys, face_w, y_eye, y_chin, breadth, crown, n_top, length)
    w0 = float(np.interp(0.0, y, w))

    neck = json.loads(json.dumps(NECK))
    nr = 0.34 * breadth
    neck["axes_xz"] = [round(nr, 1), round(nr * 50 / 52, 1)]
    neck["y"] = [NECK["y"][0], round(min(-30.0, y_chin + 45), 1)]

    meta = {"measured": True, "breadth_mm": round(breadth, 1), "bizygomatic_mm": round(bizyg, 1), "jaw_exponent": round(n_jaw, 2),
            "vault_exponent": round(n_top, 2), "sources": sources, "segmented": sil_poly is not None,
            "face_outline": {"y": ys.round(1).tolist(), "half_width": face_w.round(2).tolist()},
            "length_mm": round(length, 1), "chin_mm": round(y_chin, 1),
            "crown_mm": round(crown, 1), "eye_line_mm": round(y_eye, 1), "ipd_mm": round(ipd, 1),
            "mm_per_px": round(mm, 4), "roll_deg": round(math.degrees(roll), 1),
            "yaw_deg": None if yaw_deg is None else round(float(yaw_deg), 1)}
    shape = HeadShape(y, w, d, c, "front photo (MediaPipe face landmarks, iris scale)", neck=neck, meta=meta)

    # outline back in image pixels for the confirmation overlay: fitted silhouette + measured face oval
    def to_img(xy):
        xy = np.asarray(xy, float).copy()
        xy[:, 0] += x_mid
        xy[:, 1] += y_canal
        xy = xy / mm
        xy[:, 1] *= -1
        return (xy @ R + mid).round(1).tolist()       # R.T inverse = R for the inverse rotation
    sil = np.vstack([np.stack([w, y], 1), np.stack([-w[::-1], y[::-1]], 1)])
    report = {"warnings": warnings, "meta": meta,
              "overlay": {"silhouette_px": to_img(sil), "face_oval_px": to_img(oval),
                          "hair_outline_px": to_img(sil_poly) if sil_poly is not None else None,
                          "canal_line_px": to_img([[-w0 - 10, 0.0], [w0 + 10, 0.0]]),
                          "measured_to_px": round(float(ys.max()), 1)}}
    return shape, report


if __name__ == "__main__":
    j = json.load(open(sys.argv[1]))
    shape, rep = fit(j["landmarks"], j["image_w"], j["image_h"], j.get("yaw_deg"))
    print(json.dumps({"meta": rep["meta"], "warnings": rep["warnings"]}, indent=1))
