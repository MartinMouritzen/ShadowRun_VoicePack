#!/usr/bin/env bash
# Voice Lab: server + UI. Binds 0.0.0.0 so Windows Chrome can reach it from WSL.
cd "$(dirname "$0")"
PORT=${1:-3717}
echo "Voice Lab: http://localhost:$PORT/lab.html   (/ redirects here)"
python3 server.py "$PORT"
