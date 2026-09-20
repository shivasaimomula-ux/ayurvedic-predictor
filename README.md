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

## Pipeline handoffs (F → A → C / B)
- **Port:** `8000` (F posts to `POST /predict`; do not clash with APEX).
- **Consumes F `context`:** `spec_id`, `confidence_floor`, `safety`, `symptom_spec`
  — echoed in `f_context` + audit; floor is **never raised**.
- **Emits for C:** on `status=recommendation`, `formulation_input` matches
  dossier_engine `FormulationInput` shape with **`modernized_sku: null`**.
- **Emits for B:** `formulation_spec` (herbenzo-contracts `FormulationSpec`) when
  every herb resolves to an HB-* id and a positive `quantity_mg` (stated dose or
  CoA/demo defaults). Otherwise `formulation_spec` is null with
  `formulation_spec_error` — A does **not** invent identity or dose.
  Independent A and B UIs stay separate; this is the typed API payload only.
- Refusals (`insufficient_evidence`) omit both exports.

## Configuration (.env)
Copy `.env.example` → `.env` (never commit secrets).
- `GEMINI_API_KEY` — generator (default).
- `ANTHROPIC_API_KEY` — optional; verifier prefers Claude when set
  (trust-critical verify only).
- Other knobs (models, iterations, A→C demo defaults): see `predictor/config.py`.

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
