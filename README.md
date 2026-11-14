# HackPrincetonFall2026 · passive horn hearing aid (ear-labs)

| Folder | What |
|---|---|
| `backend/` | FastAPI server: photo → 3D ear (AudioEar) → patient context (HASPI references) → 3D in-ear horn aid. Dockerfile included. See `backend/README.md`. |
| `frontend/` | Static page: upload an ear photo, draw a box around the ear, enter a hearing test, watch the build, inspect the aid in 3D, download the STL. Served by the backend at `/`. |

Quick start: `git submodule update --init`, then follow `backend/README.md`.
