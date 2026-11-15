# Auris

<img width="1926" height="1232" alt="auris" src="https://github.com/user-attachments/assets/a831f355-8572-4460-9bc5-e83f83396ca7" />

A personalized passive acoustic hearing device: a printed horn whose geometry is chosen for a modeled hearing profile and the user's intended use.

## Layout

| Path | Contents |
| --- | --- |
| [`agents/`](agents/README.md) | Research and experiment-planning agent system, evaluator adapter, events and artifacts for the frontend, LangSmith tracing |
| [`backend/`](backend/README.md) | FastAPI server: ear photo to 3D ear (AudioEar), patient context (HASPI references), 3D in-ear horn aid. Dockerfile included. |
| `frontend/` | Auris Next.js app, plus `index.html`, `app.js` and `styles.css`: a static page for the backend that the backend serves at `/`. |

Backend quick start: `git submodule update --init`, then follow `backend/README.md`.
