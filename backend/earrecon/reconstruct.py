"""Single photo -> 3D ear mesh with the pretrained AudioEarM model (Huang et al., AAAI 2023).

Runs only AudioEar's two networks (FCRN depth net + ResNet encoder) and its ear PCA
model; the PyTorch3D renderer is only needed for training, so it is not used. SAM 2
cuts the ear out of the photo from a box prompt.

    python -m earrecon.reconstruct photo.jpg --box x0,y0,x1,y1 [--left] [--height-mm 62] [--out dir]

Paths (override with env vars):
    AUDIOEAR_DIR  third_party/AudioEar (git submodule: FCRN.py, data/)
    WEIGHTS_DIR   weights/ (encoder.pt, frcn.pt, sam2.1_b.pt; see scripts/fetch_weights.sh)
"""
import argparse
import functools
import os
import pickle
import sys
import threading

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision.models as models
import trimesh

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIOEAR_DIR = os.environ.get("AUDIOEAR_DIR", os.path.join(BACKEND, "third_party", "AudioEar"))
WEIGHTS_DIR = os.environ.get("WEIGHTS_DIR", os.path.join(BACKEND, "weights"))
LANDMARKS_XLSX = os.path.join(AUDIOEAR_DIR, "data", "55_landmarks.xlsx")
IMG = 256

sys.path.insert(0, AUDIOEAR_DIR)
import FCRN  # noqa: E402  (from the AudioEar submodule)


def _unpool_forward(self, x):  # upstream Unpool hard-codes CPU/CUDA; follow the input's device (MPS)
    w = torch.zeros(self.num_channels, 1, self.stride, self.stride, device=x.device, dtype=x.dtype)
    w[:, :, 0, 0] = 1
    return torch.nn.functional.conv_transpose2d(x, w, stride=self.stride, groups=self.num_channels)


FCRN.Unpool.forward = _unpool_forward


class ResNet_FCRN(nn.Module):
    """Copied from AudioEar models.py (which imports pytorch3d at top level)."""

    def __init__(self):
        super().__init__()
        r = models.resnet18(weights=None)
        self.conv1, self.bn1, self.relu, self.maxpool = r.conv1, r.bn1, r.relu, r.maxpool
        self.layer1, self.layer2, self.layer3, self.layer4 = r.layer1, r.layer2, r.layer3, r.layer4
        self.avgpool = r.avgpool
        self.layer1_conv = nn.Conv2d(64 + 16, 64, 3, 1, 1)
        self.layer2_conv = nn.Conv2d(64 + 32, 64, 3, 1, 1)
        self.layer3_conv = nn.Conv2d(128 + 64, 128, 3, 1, 1)
        self.layer4_conv = nn.Conv2d(256 + 128, 256, 3, 1, 1)
        self.fc = nn.Linear(512, 34)
        self.fc_tex = nn.Linear(512, 50)
        self.shape_fc = nn.Sequential(
            nn.Linear(512, 1024), nn.BatchNorm1d(1024), nn.LeakyReLU(),
            nn.Linear(1024, 512), nn.BatchNorm1d(512), nn.LeakyReLU(),
            nn.Linear(512, 236),
        )

    def forward(self, x, f):
        x = self.maxpool(self.relu(self.bn1(self.conv1(x))))
        x = self.layer1(self.layer1_conv(torch.cat([x, self.maxpool(f[-1])], 1)))
        x = self.layer2(self.layer2_conv(torch.cat([x, f[-2]], 1)))
        x = self.layer3(self.layer3_conv(torch.cat([x, f[-3]], 1)))
        x = self.layer4(self.layer4_conv(torch.cat([x, f[-4]], 1)))
        x = torch.flatten(self.avgpool(x), 1)
        return self.fc(x), self.fc_tex(x), self.shape_fc(x)


def device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


_lock = threading.Lock()


@functools.lru_cache(maxsize=1)
def models_():
    """Load once per process: depth net, encoder, ear PCA model, SAM 2."""
    from ultralytics import SAM
    dev = device()
    fcrn = FCRN.ResNet(layers=34, output_size=(IMG, IMG), pretrained=False)
    fcrn.load_state_dict(torch.load(os.path.join(WEIGHTS_DIR, "frcn.pt"), map_location="cpu"))
    enc = ResNet_FCRN()
    enc.load_state_dict(torch.load(os.path.join(WEIGHTS_DIR, "encoder.pt"), map_location="cpu"))
    pca = pickle.load(open(os.path.join(AUDIOEAR_DIR, "data", "UHM_models", "ear_model.pkl"), "rb"))
    sam = SAM(os.path.join(WEIGHTS_DIR, "sam2.1_b.pt"))
    return dev, fcrn.to(dev).eval(), enc.to(dev).eval(), pca, sam


def euler_xyz(a):
    """Same convention as pytorch3d euler_angles_to_matrix(a, 'XYZ')."""
    cx, cy, cz = np.cos(a)
    sx, sy, sz = np.sin(a)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rx @ Ry @ Rz


def sam_mask(sam, img_rgb, box, point):
    # a box around the ear is what makes SAM pick the ear instead of the whole head
    res = sam(img_rgb[:, :, ::-1], bboxes=[box], points=[point], labels=[1], verbose=False)[0]
    masks = sorted(res.masks.data.cpu().numpy().astype(bool), key=lambda m: -m.sum())
    for m in masks:
        if m[point[1], point[0]]:
            return m
    return masks[0]


def square_crop(img, mask, pad_frac):
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    side = int(max(x1 - x0, y1 - y0) * (1 + 2 * pad_frac))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    P = side
    img_p = cv2.copyMakeBorder(img, P, P, P, P, cv2.BORDER_CONSTANT, value=0)
    mask_p = cv2.copyMakeBorder(mask.astype(np.uint8), P, P, P, P, cv2.BORDER_CONSTANT, value=0)
    sx, sy = cx - side // 2 + P, cy - side // 2 + P
    return img_p[sy:sy + side, sx:sx + side], mask_p[sy:sy + side, sx:sx + side]


def _canonical(m, shape):
    """PCA shape coefficients -> vertices in AudioEar's canonical frame (+x lateral, +y up, -z forward
    for a right ear), centred, in model units. Returns (verts, faces)."""
    verts = (m["Mean"][:, 0] + m["Eigenvectors"] @ (shape * m["EigenValues"])).reshape(-1, 3)
    faces = np.asarray(m["Trilist"], dtype=np.int64)
    if faces.min() == 1:
        faces = faces - 1
    verts = verts - (verts.min(0) + verts.max(0)) / 2      # same canonicalisation as AudioEar utils
    verts[:, 0] *= -1
    verts[:, 2] *= -1
    return verts, faces


def save_depth(depth, mask, path):
    """depth.png: the depth FCRN predicts from the photo (AudioEar's first network), inside the ear mask.
    Colour is RELATIVE depth (2nd-98th percentile in the mask), nearest the camera brightest; no units —
    FCRN's output is not metric. Display only; the mesh comes from the second network."""
    import matplotlib
    # the mask's ragged edge (hair, earring) gives specks: open it, then keep only the largest region
    m = cv2.morphologyEx((mask > 0).astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return
    m = lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    # FCRN's deconvolutions leave dot artifacts on a regular grid, up to ~12 px wide at 256 px: replace pixels that
    # stand out from a 15 px median, then a light median for the rest
    from scipy.ndimage import median_filter
    d = depth.astype(np.float32)
    big = median_filter(d, size=15)
    dev = np.abs(d - big)
    d = np.where(dev > 3 * np.median(dev[m]), big, d)
    d = cv2.medianBlur(d, 5)
    lo, hi = np.percentile(d[m], [2, 98])
    t = np.clip((hi - d) / (hi - lo + 1e-9), 0, 1)        # LOW FCRN values are near the camera (checked: concha darkest)
    rgb = (matplotlib.colormaps["inferno"](t)[..., :3] * 255).astype(np.uint8)
    rgb[~m] = 0
    rgb = cv2.resize(rgb, (512, 512), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def mean_ear(out, height_mm=62.0):
    """The PCA model's average right ear, scaled to `height_mm`. A stand-in when no photo has been
    reconstructed yet; it is NOT anyone's ear. Writes <out>/ear.ply and returns its path."""
    m = pickle.load(open(os.path.join(AUDIOEAR_DIR, "data", "UHM_models", "ear_model.pkl"), "rb"))
    verts, faces = _canonical(m, np.zeros(len(m["EigenValues"])))
    verts = verts * (height_mm / np.ptp(verts[:, 1]))
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "ear.ply")
    trimesh.Trimesh(verts, faces, process=False).export(path)
    return path


def _fit(dev, fcrn, enc, m, img, mask, left, pad):
    """The networks on one ear photo: a left ear is mirrored first (the model is of right ears). Returns
    the crop, the posed model's vertices projected into it, and which of them land inside the ear mask."""
    if left:
        img, mask = img[:, ::-1].copy(), mask[:, ::-1].copy()
    crop, cmask = square_crop(img, mask, pad)
    crop = cv2.resize(crop, (IMG, IMG), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
    cmask = cv2.resize(cmask, (IMG, IMG), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    x = crop * cmask[..., None]
    with torch.no_grad():
        t = torch.from_numpy(x).permute(2, 0, 1)[None].to(dev)
        _, feats = fcrn(t)
        pos, _, shape = enc(t, feats)
    pos, shape = pos[0].cpu().numpy(), shape[0].cpu().numpy()
    verts, faces = _canonical(m, shape)
    # posed verts -> pixels (pytorch3d look_at_view_transform(10, 0, pi/2) + orthographic camera)
    f = pos[5]
    posed = (euler_xyz(pos[:3]) @ (verts * f).T).T
    posed[:, 1:] += pos[3:5] * f
    px = np.stack([IMG / 2 - IMG / 2 * posed[:, 2], IMG / 2 - IMG / 2 * posed[:, 1]], 1)
    pxi = np.clip(px.round().astype(int), 0, IMG - 1)
    inside = cmask[pxi[:, 1], pxi[:, 0]] > 0
    return {"crop": crop, "cmask": cmask, "x": x, "pos": pos, "shape": shape, "verts": verts, "faces": faces,
            "pxi": pxi, "inside": inside}


def mask_for(photo, box):
    """The photo (RGB, EXIF already applied by the API) and SAM 2's ear mask inside `box`."""
    img = cv2.imread(photo)
    if img is None:
        raise ValueError("could not read the photo")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, x1 = max(0, min(x0, x1)), min(w - 1, max(x0, x1))
    y0, y1 = max(0, min(y0, y1)), min(h - 1, max(y0, y1))
    if x1 - x0 < 20 or y1 - y0 < 20:
        raise ValueError("box is too small; draw it tightly around the ear")
    with _lock:
        _, _, _, _, sam = models_()
        mask = sam_mask(sam, img, [x0, y0, x1, y1], ((x0 + x1) // 2, (y0 + y1) // 2))
    if mask.sum() < 400:
        raise ValueError("could not find the ear inside the box")
    return img, mask


def classify_side(photo, box, pad=0.15):
    """Which ear is this? The model only knows right ears, so fit the photo as it is (a right ear) and
    mirrored (a left ear): the reading whose posed model lands better inside the ear's outline wins.
    Returns {"side", "fit": {"right", "left"}, "margin"}; a small margin means the photo cannot tell."""
    img, mask = mask_for(photo, box)
    with _lock:
        dev, fcrn, enc, m, _ = models_()
        fit = {side: float(_fit(dev, fcrn, enc, m, img, mask, side == "left", pad)["inside"].mean())
               for side in ("right", "left")}
    side = max(fit, key=fit.get)
    return {"side": side, "fit": {k: round(v, 3) for k, v in fit.items()}, "margin": round(abs(fit["right"] - fit["left"]), 3)}


def reconstruct(photo, out, box, left=False, height_mm=62.0, pad=0.15, mask_path=None, log=print):
    """Photo -> ear mesh in `out`. `box` = [x0, y0, x1, y1] around the ear in full-resolution pixels.

    Returns a summary dict. Writes ear.obj/.ply/.glb, mask.png, input.jpg, overlay.jpg, params.npz.
    """
    os.makedirs(out, exist_ok=True)
    img = cv2.imread(photo)
    if img is None:
        raise ValueError("could not read the photo")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    with _lock:  # models are shared; one inference at a time
        dev, fcrn, enc, m, sam = models_()
        if mask_path:
            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE) > 127
        else:
            x0, y0, x1, y1 = [int(v) for v in box]
            x0, x1 = max(0, min(x0, x1)), min(w - 1, max(x0, x1))
            y0, y1 = max(0, min(y0, y1)), min(h - 1, max(y0, y1))
            if x1 - x0 < 20 or y1 - y0 < 20:
                raise ValueError("box is too small; draw it tightly around the ear")
            mask = sam_mask(sam, img, [x0, y0, x1, y1], ((x0 + x1) // 2, (y0 + y1) // 2))
        if mask.sum() < 400:
            raise ValueError("could not find the ear inside the box")
        cv2.imwrite(os.path.join(out, "mask.png"), mask.astype(np.uint8) * 255)
        if left:
            img, mask = img[:, ::-1].copy(), mask[:, ::-1].copy()
        # The networks only see right ears, so a left ear is fitted MIRRORED — but every image a person sees (input, overlay, depth) is flipped back, or their own ear is shown backwards.
        shown = (lambda a: np.ascontiguousarray(a[:, ::-1])) if left else (lambda a: a)

        crop, cmask = square_crop(img, mask, pad)
        crop = cv2.resize(crop, (IMG, IMG), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
        cmask = cv2.resize(cmask, (IMG, IMG), interpolation=cv2.INTER_NEAREST).astype(np.float32)
        x = crop * cmask[..., None]
        cv2.imwrite(os.path.join(out, "input.jpg"), cv2.cvtColor(shown((x * 255).astype(np.uint8)), cv2.COLOR_RGB2BGR))
        with torch.no_grad():
            t = torch.from_numpy(x).permute(2, 0, 1)[None].to(dev)
            depth, feats = fcrn(t)
            pos, _, shape = enc(t, feats)
        pos, shape = pos[0].cpu().numpy(), shape[0].cpu().numpy()
        depth = depth[0, 0].cpu().numpy()

    verts, faces = _canonical(m, shape)

    # posed verts -> pixels (pytorch3d look_at_view_transform(10, 0, pi/2) + orthographic camera)
    f = pos[5]
    posed = (euler_xyz(pos[:3]) @ (verts * f).T).T
    posed[:, 1:] += pos[3:5] * f
    px = np.stack([IMG / 2 - IMG / 2 * posed[:, 2], IMG / 2 - IMG / 2 * posed[:, 1]], 1)
    pxi = np.clip(px.round().astype(int), 0, IMG - 1)
    colors = crop[pxi[:, 1], pxi[:, 0]]
    if inside.any():
        colors[~inside] = colors[inside].mean(0)
    ov = (crop * 255).astype(np.uint8).copy()
    for u, v in pxi[::4]:
        cv2.circle(ov, (int(u), int(v)), 1, (0, 255, 0), -1)
    cv2.imwrite(os.path.join(out, "overlay.jpg"), cv2.cvtColor(shown(ov), cv2.COLOR_RGB2BGR))
    save_depth(shown(depth), shown(cmask), os.path.join(out, "depth.png"))

    verts = verts * (height_mm / np.ptp(verts[:, 1]))
    if left:
        verts[:, 2] *= -1
        faces = faces[:, ::-1]
    mesh = trimesh.Trimesh(verts, faces, vertex_colors=(colors * 255).astype(np.uint8), process=False)
    for ext in ("obj", "ply", "glb"):
        mesh.export(os.path.join(out, f"ear.{ext}"))
    np.savez(os.path.join(out, "params.npz"), pose=pos, shape=shape)
    summary = {"fit_inside_mask": round(float(inside.mean()), 3), "extent_mm": np.round(mesh.extents, 1).tolist(),
               "side": "left" if left else "right", "height_mm": height_mm, "photo_size": [w, h]}
    log(f"ear: {summary['fit_inside_mask']:.0%} of vertices inside the mask, extent {summary['extent_mm']} mm")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1 around the ear (full-resolution pixels)")
    ap.add_argument("--left", action="store_true")
    ap.add_argument("--height-mm", type=float, default=62.0)
    ap.add_argument("--out", default="out/ear")
    a = ap.parse_args()
    print(reconstruct(a.photo, a.out, [int(v) for v in a.box.split(",")], a.left, a.height_mm))
