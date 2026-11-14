#!/usr/bin/env bash
# Download model weights into $WEIGHTS_DIR (default: backend/weights).
#   AudioEar encoder + depth net: the AudioEar README's Google Drive folder
#   SAM 2.1 base: Ultralytics release
set -euo pipefail
cd "$(dirname "$0")/.."
W="${WEIGHTS_DIR:-weights}"
mkdir -p "$W"
[ -f "$W/encoder.pt" ]  || gdown 1J5Hx2XDxVGYdB1egKDQ74AtMhGfvSgFm -O "$W/encoder.pt"
[ -f "$W/frcn.pt" ]     || gdown 19jJnpK24GawdHQbKP-PEobXLpMz24N5l -O "$W/frcn.pt"
[ -f "$W/sam2.1_b.pt" ] || curl -fL -o "$W/sam2.1_b.pt" https://github.com/ultralytics/assets/releases/download/v8.4.0/sam2.1_b.pt
ls -la "$W"
