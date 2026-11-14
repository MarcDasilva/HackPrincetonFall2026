# Build from the repo root so the frontend is included:
#   git submodule update --init
#   docker build -f backend/Dockerfile -t horn-aid .
#   docker run -p 8000:8000 -v horn-data:/data horn-aid
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsndfile1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend
COPY backend/requirements.txt .
# CPU-only PyTorch keeps the image small; use a CUDA base image + wheel for GPU hosts.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/ /srv/backend/
COPY frontend/ /srv/frontend/
RUN test -f third_party/AudioEar/FCRN.py || (echo "AudioEar submodule missing: run 'git submodule update --init'" && exit 1)

ARG FETCH_WEIGHTS=1
RUN if [ "$FETCH_WEIGHTS" = "1" ]; then ./scripts/fetch_weights.sh; fi

ENV DATA_DIR=/data FRONTEND_DIR=/srv/frontend YOLO_CONFIG_DIR=/tmp/ultralytics MPLCONFIGDIR=/tmp/mpl
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
