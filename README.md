# Ayurvedic Predictive Model

Standalone, agentic, evidence-verified Ayurvedic recommendation engine.
Given a symptom, it proposes a classical formulation (formula + formulation +
delivery system) and **substantiates every claim against live PubMed evidence**
with a cross-model verifier — or honestly returns *insufficient evidence*.

Independent of the Herbenzo / APEX projects.

## Quick start

```bash
cd ~/Desktop/ayurvedic-predictor
pip install -r requirements.txt        # first time only
./run.sh                               # or: python3 -m uvicorn predictor.api:app --port 8000
```

Then open **http://127.0.0.1:8000** in your browser — type a symptom, hit Analyze.

## Three ways to use it
- **Web UI:** http://127.0.0.1:8000
- **API docs:** http://127.0.0.1:8000/docs  (interactive `POST /predict`)
- **CLI:** `python3 -m predictor.cli "constant stress and can't sleep"`

A query takes ~30–90 s (live literature search + per-claim verification).

## Configuration (.env)
- `GEMINI_API_KEY` — required (already present).
- `ANTHROPIC_API_KEY` — optional; if set, the verifier auto-switches to Claude
  for true **cross-provider** verification. No code change needed.
- Other knobs (models, iterations, thresholds): see `predictor/config.py`.

## Layout
```
ayurvedic-predictor/
├── predictor/      # the engine (connectors, agents, pipeline, api, cli)
├── web/index.html  # single-page UI
├── run.sh
├── requirements.txt
└── .env
```

See `predictor/README.md` for the architecture → code map and scope notes.
