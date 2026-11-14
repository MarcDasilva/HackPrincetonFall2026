# photo_to_ear

One ear photo → 3D ear mesh (`ear.obj` / `ear.ply` / `ear.glb`, in mm), using the pretrained
[AudioEar](https://github.com/seanywang0408/AudioEar) model (Huang et al., AAAI 2023). Runs on a Mac
(Apple GPU via MPS) without CUDA or PyTorch3D.

## Setup

```bash
git clone https://github.com/seanywang0408/AudioEar repos/AudioEar
cp photo_to_ear/photo_to_ear.py repos/AudioEar/
cd repos/AudioEar
uv venv -p 3.12 .venv
uv pip install -p .venv torch torchvision opencv-python numpy trimesh pillow ultralytics gdown
mkdir -p weights
.venv/bin/gdown 1J5Hx2XDxVGYdB1egKDQ74AtMhGfvSgFm -O weights/encoder.pt
.venv/bin/gdown 19jJnpK24GawdHQbKP-PEobXLpMz24N5l -O weights/frcn.pt
```

SAM 2 (`sam2.1_b.pt`) downloads on first run; move it into `weights/` afterwards.

## Run

```bash
.venv/bin/python photo_to_ear.py ear.jpg --height-mm 62          # drag a box around the ear
.venv/bin/python photo_to_ear.py ear.jpg --left --box x0,y0,x1,y1  # left ear, box given
```

Outputs go to `out/<photo name>/`: the mesh files plus `mask.png` and `overlay.jpg` to check the cut-out and fit.

## Limits

- The released encoder barely personalises shape: across 29 AudioEar3D subjects, predictions differ from
  the average by a median of 0.3 mm. Treat the mesh as a well-fitted template ear.
- One photo cannot give real size; `--height-mm` scales it (measure the ear, top to lobe).
- Only the visible ear is modelled; the ear canal is not.
