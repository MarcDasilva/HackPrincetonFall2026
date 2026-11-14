"""Single photo -> 3D ear mesh, using the pretrained AudioEarM weights.

This script needs neither PyTorch3D nor CUDA. It runs only the two networks
(FCRN depth net + ResNet encoder) and the ear PCA model. The renderer is only
needed for training, so it is skipped.

Usage:
    python photo_to_ear.py ear.jpg                      # right ear; drag a box around it
    python photo_to_ear.py ear.jpg --left               # photo of a left ear
    python photo_to_ear.py ear.jpg --box 300,200,700,820  # box given up front (px)
    python photo_to_ear.py ear.jpg --mask ear_mask.png  # your own mask instead of SAM

Outputs, in --out (default: out/<photo name>/):
    ear.obj / ear.ply / ear.glb   mesh with vertex colours sampled from the photo
    mask.png                      the ear mask SAM produced (check it!)
    input.jpg                     the 256x256 masked crop the network saw
    overlay.jpg                   predicted mesh projected onto the crop (sanity check)
"""
import argparse
import os
import pickle

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision.models as models
import trimesh

import FCRN

def _unpool_forward(self, x):  # upstream Unpool hard-codes CPU/CUDA; follow the input's device (MPS)
    w = torch.zeros(self.num_channels, 1, self.stride, self.stride, device=x.device, dtype=x.dtype)
    w[:, :, 0, 0] = 1
    return torch.nn.functional.conv_transpose2d(x, w, stride=self.stride, groups=self.num_channels)


FCRN.Unpool.forward = _unpool_forward

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = 256


class ResNet_FCRN(nn.Module):
    """Copied from models.py (which imports pytorch3d at top level)."""

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


def euler_xyz(a):
    """Same convention as pytorch3d euler_angles_to_matrix(a, 'XYZ')."""
    cx, cy, cz = np.cos(a)
    sx, sy, sz = np.sin(a)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rx @ Ry @ Rz


def sam_mask(img_rgb, box, point):
    from ultralytics import SAM
    local = os.path.join(HERE, "weights", "sam2.1_b.pt")
    sam = SAM(local if os.path.exists(local) else "sam2.1_b.pt")  # name only -> auto-download
    # a box around the ear is what makes SAM pick the ear instead of the whole head
    res = sam(img_rgb[:, :, ::-1], bboxes=[box], points=[point], labels=[1], verbose=False)[0]
    masks = res.masks.data.cpu().numpy().astype(bool)
    # SAM may return several candidates; keep the one containing the point, largest first
    masks = sorted(masks, key=lambda m: -m.sum())
    for m in masks:
        if m[point[1], point[0]]:
            return m
    return masks[0]


def square_crop(img, mask, pad_frac):
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    side = int(max(x1 - x0, y1 - y0) * (1 + 2 * pad_frac))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    h, w = mask.shape
    # pad the image so the square never goes out of bounds
    P = side
    img_p = cv2.copyMakeBorder(img, P, P, P, P, cv2.BORDER_CONSTANT, value=0)
    mask_p = cv2.copyMakeBorder(mask.astype(np.uint8), P, P, P, P, cv2.BORDER_CONSTANT, value=0)
    sx, sy = cx - side // 2 + P, cy - side // 2 + P
    return img_p[sy:sy + side, sx:sx + side], mask_p[sy:sy + side, sx:sx + side]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--left", action="store_true", help="photo shows a LEFT ear (model expects right; we mirror)")
    ap.add_argument("--box", help="x0,y0,x1,y1 box around the ear, in pixels (default: drag one in a window)")
    ap.add_argument("--point", help="x,y pixel on the ear for SAM (default: centre of the box)")
    ap.add_argument("--mask", help="binary mask image (white = ear) instead of SAM")
    ap.add_argument("--pad", type=float, default=0.15, help="crop padding around the ear, fraction of its size")
    ap.add_argument("--height-mm", type=float, default=62.0,
                    help="scale mesh so the ear is this tall (one photo cannot recover absolute size; measure yours)")
    ap.add_argument("--out")
    a = ap.parse_args()

    out = a.out or os.path.join("out", os.path.splitext(os.path.basename(a.photo))[0])
    os.makedirs(out, exist_ok=True)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    img = cv2.cvtColor(cv2.imread(a.photo), cv2.COLOR_BGR2RGB)
    if a.mask:
        mask = cv2.imread(a.mask, cv2.IMREAD_GRAYSCALE) > 127
    else:
        if a.box:
            box = [int(v) for v in a.box.split(",")]
        else:
            print("Drag a box tightly around the ear, then press ENTER (c = cancel).")
            x, y, bw, bh = cv2.selectROI("select ear", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), showCrosshair=False)
            cv2.destroyAllWindows()
            if bw == 0 or bh == 0:
                raise SystemExit("no box selected")
            box = [x, y, x + bw, y + bh]
            print(f"box: --box {box[0]},{box[1]},{box[2]},{box[3]}")
        pt = tuple(int(v) for v in a.point.split(",")) if a.point else ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        mask = sam_mask(img, box, pt)
    cv2.imwrite(os.path.join(out, "mask.png"), mask.astype(np.uint8) * 255)
    if a.left:
        img, mask = img[:, ::-1].copy(), mask[:, ::-1].copy()

    crop, cmask = square_crop(img, mask, a.pad)
    crop = cv2.resize(crop, (IMG, IMG), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
    cmask = cv2.resize(cmask, (IMG, IMG), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    x = crop * cmask[..., None]
    cv2.imwrite(os.path.join(out, "input.jpg"), cv2.cvtColor((x * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))

    fcrn = FCRN.ResNet(layers=34, output_size=(IMG, IMG), pretrained=False)
    fcrn.load_state_dict(torch.load(os.path.join(HERE, "weights", "frcn.pt"), map_location="cpu"))
    enc = ResNet_FCRN()
    enc.load_state_dict(torch.load(os.path.join(HERE, "weights", "encoder.pt"), map_location="cpu"))
    fcrn, enc = fcrn.to(dev).eval(), enc.to(dev).eval()

    with torch.no_grad():
        t = torch.from_numpy(x).permute(2, 0, 1)[None].to(dev)
        _, feats = fcrn(t)
        pos, _, shape = enc(t, feats)
    pos, shape = pos[0].cpu().numpy(), shape[0].cpu().numpy()

    m = pickle.load(open(os.path.join(HERE, cfg_pkl()), "rb"))
    verts = (m["Mean"][:, 0] + m["Eigenvectors"] @ (shape * m["EigenValues"])).reshape(-1, 3)
    faces = np.asarray(m["Trilist"], dtype=np.int64)
    if faces.min() == 1:
        faces = faces - 1
    # same canonicalisation as utils.deform_scale_rotation
    verts = verts - (verts.min(0) + verts.max(0)) / 2
    verts[:, 0] *= -1
    verts[:, 2] *= -1

    # posed verts -> pixel coords, to colour the mesh and draw the sanity overlay.
    # Camera = pytorch3d look_at_view_transform(10, 0, pi/2) + FoVOrthographic:
    # view x = world z, view y = world y; pixel = -ndc * 128 + 128.
    f = pos[5]
    posed = (euler_xyz(pos[:3]) @ (verts * f).T).T
    posed[:, 1:] += pos[3:5] * f
    px = np.stack([IMG / 2 - IMG / 2 * posed[:, 2], IMG / 2 - IMG / 2 * posed[:, 1]], 1)
    pxi = np.clip(px.round().astype(int), 0, IMG - 1)
    colors = crop[pxi[:, 1], pxi[:, 0]]
    inside = cmask[pxi[:, 1], pxi[:, 0]] > 0
    if inside.any():  # vertices that land off the ear get the mean ear colour
        colors[~inside] = colors[inside].mean(0)
    print(f"{inside.mean():.0%} of mesh vertices project inside the ear mask (higher = better fit)")

    ov = (crop * 255).astype(np.uint8).copy()
    for u, v in pxi[::4]:
        cv2.circle(ov, (int(u), int(v)), 1, (0, 255, 0), -1)
    cv2.imwrite(os.path.join(out, "overlay.jpg"), cv2.cvtColor(ov, cv2.COLOR_RGB2BGR))

    # model space: y = up. Scale to requested height, in millimetres.
    verts = verts * (a.height_mm / (verts[:, 1].max() - verts[:, 1].min()))
    if a.left:
        verts[:, 2] *= -1  # mirror back to a left ear
        faces = faces[:, ::-1]
    mesh = trimesh.Trimesh(verts, faces, vertex_colors=(colors * 255).astype(np.uint8), process=False)
    for ext in ("obj", "ply", "glb"):
        mesh.export(os.path.join(out, f"ear.{ext}"))
    np.savez(os.path.join(out, "params.npz"), pose=pos, shape=shape)
    print("extent (mm):", np.round(mesh.extents, 1), "->", os.path.abspath(out))


def cfg_pkl():
    return os.path.join("data", "UHM_models", "ear_model.pkl")


if __name__ == "__main__":
    main()
