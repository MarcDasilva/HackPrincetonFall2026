# Backend

FastAPI server for the horn-aid pipeline: **photo → ear mesh → patient context → 3D in-ear aid**.

```
backend/
  app/            HTTP API + background job runner
  earrecon/       photo -> 3D ear mesh (AudioEar networks + SAM 2), see earrecon/README.md
  hornsim/        ear fit space, canal samples, HASPI references, 3D aid builder, see HORNSIM.md
  third_party/AudioEar   git submodule (pinned upstream commit; no licence file upstream, so not vendored)
  assets/speech/  cached test-speech clips (generated with macOS `say`; reused on Linux)
  scripts/fetch_weights.sh
  Dockerfile
```

## Run locally

```bash
git submodule update --init                 # AudioEar code + ear model data
cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
PATH=.venv/bin:$PATH ./scripts/fetch_weights.sh   # ~310 MB into weights/
.venv/bin/uvicorn app.main:app --port 8000
```

Open http://localhost:8000 for the frontend (served from `../frontend`).
Uses CUDA, Apple MPS or CPU automatically. A full run takes about 2-3 minutes; most of it is the
aid geometry search and HASPI references, not the networks.

## Host it

```bash
git submodule update --init
docker build -f backend/Dockerfile -t horn-aid .      # from the repo root
docker run -p 8000:8000 -v horn-data:/data horn-aid
```

The image is CPU-only PyTorch and downloads weights at build time (`--build-arg FETCH_WEIGHTS=0`
to skip and mount them at `/srv/backend/weights` instead). Any container host works (Fly.io,
Render, Railway, a VM). Give it ~4 GB RAM. Patient data goes to `DATA_DIR` (`/data` in the image); mount a volume.

Environment: `DATA_DIR`, `WEIGHTS_DIR`, `AUDIOEAR_DIR`, `FRONTEND_DIR`, `WORKERS` (default 1),
`MAX_UPLOAD_MB` (25), `CORS_ORIGINS` (comma list, default `*`). To host the frontend separately,
point it at the API with `?api=https://your-api` or `window.API_BASE`.

## API

| Method | Path | Body / result |
|---|---|---|
| GET | `/api/health` | weights and AudioEar present |
| POST | `/api/patients` | multipart: `photo`, `box` (`x0,y0,x1,y1` px after EXIF rotation; blank = detected), `side` (`left`/`right`, the person's own ear; blank = detected), `ear_height_mm`, `audiogram` (JSON dB HL, or `{"left": {...}, "right": {...}}` so the detected ear picks; blank = example) → `{id}` (202) |
| GET | `/api/patients/{id}` | `status` (queued/running/done/error), `step`, `log`, `results` (ear, context, aid), `files` |
| POST | `/api/patients/{id}/aid` | JSON `throat_mm2`, `mouth_mm2`, `vent_diameter_mm` (0 = no vent), `min_wall_mm`, `max_path_mm`, `tip_clearance_mm` → rebuilds the aid |
| GET | `/api/patients/{id}/files/{name}` | `ear.glb`, `overlay.jpg`, `mask.png`, `summary.png`, `aid.glb`, `aid_in_ear.glb`, `aid_print.stl`, `design.json`, `references.json`, … |

Example:

```bash
curl -F photo=@ear.jpg -F box=585,340,2240,3310 -F side=right -F ear_height_mm=62 \
     -F 'audiogram={"250":15,"500":20,"1000":30,"2000":45,"4000":55,"6000":55}' \
     http://localhost:8000/api/patients
```

## Ear detection (sends the photo to Anthropic)

When a request leaves `box` or `side` blank, `earrecon/detect.py` sends the photo to Claude to find the ear and its side.
It needs `ANTHROPIC_API_KEY` (503 without it) and takes `EAR_DETECT_MODEL` (default `claude-sonnet-5-5`). A client that
sends BOTH `box` and `side` never triggers a call, so an offline or private deployment can require the client to draw the box.

## Licences and limits

- **AudioEar** (Huang et al., AAAI 2023) has no licence file; it is included as a submodule, not copied.
  Its ear model data (`ear_model.pkl`) may carry its own terms. Check before commercial use.
- **pyclarity** (HASPI, NAL-R) is MIT. **SAM 2** weights via Ultralytics (AGPL-3.0 for the package).
- No authentication: put it behind a private network or add auth before sharing a public URL.
  Uploaded photos are biometric data; treat `DATA_DIR` accordingly.
- Canal opening and the HASPI audiogram default are assumptions; see HORNSIM.md.
