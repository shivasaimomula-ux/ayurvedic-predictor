#!/usr/bin/env bash
# Start the Ayurvedic Predictive Model (API + web UI) on http://127.0.0.1:8000
cd "$(dirname "$0")"
exec python3 -m uvicorn predictor.api:app --host 127.0.0.1 --port 8000
