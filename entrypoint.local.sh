#!/bin/sh
# Install the ajna-cloud-sdk from the bind-mounted source tree (editable install).
# Runs every container start so SDK changes are always picked up without rebuilds.
set -e

SDK_DIR="/ajna-cloud-sdk"

if [ -d "$SDK_DIR" ]; then
  echo "[entrypoint] Installing ajna-cloud-sdk from $SDK_DIR (editable) ..."
  pip install -e "$SDK_DIR" --quiet
else
  echo "[entrypoint] WARNING: $SDK_DIR not found — falling back to PyPI ajna-cloud."
  pip install --quiet "ajna-cloud>=0.4.66"
fi

echo "[entrypoint] Starting uvicorn with hot-reload on port 8000 ..."
exec uvicorn local_dev:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/src
