#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[setup] Created .env from .env.example — fill in your keys."
else
  echo "[setup] .env already exists, skipping."
fi
pip3 install -q -r requirements.txt
echo "[setup] Done."
