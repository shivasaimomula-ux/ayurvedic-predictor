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

## Pipeline handoffs (F → A → C)
- **Port:** `8000` (F posts to `POST /predict`; do not clash with APEX).
- **Consumes F `context`:** `spec_id`, `confidence_floor`, `safety`, `symptom_spec`
  — echoed in `f_context` + audit; floor is **never raised**.
- **Emits for C:** on `status=recommendation`, `formulation_input` matches
  dossier_engine `FormulationInput` shape with **`modernized_sku: null`**
  (B Modernizer skipped). Refusals omit the export.

## Configuration (.env)
Copy `.env.example` → `.env` (never commit secrets).

**Verifier cost order (Task T15 / Finding #11):** `NVIDIA (NIM) > Gemini > Claude`

1. Prefer blue adjudication on `:8011` when `ADJUDICATION_PREFERRED=1` and reachable.
2. Else local cheap path: NIM (if `NVIDIA_API_KEY`) → Gemini (`VERIFIER_MODEL`, default `gemini-2.5-pro`).
3. Claude (`ESCALATE_MODEL`) **only** on cheap-provider disagreement or forced hard-reject — never the default volume verifier.

| Var | Role |
|-----|------|
| `GEMINI_API_KEY` | Generator + cheap Gemini verifier |
| `NVIDIA_API_KEY` | Optional NIM cheap verifier (preferred when set) |
| `ANTHROPIC_API_KEY` | Optional Claude escalate only |
| `ADJUDICATION_URL` | Blue service (default `http://127.0.0.1:8011`) |

Other knobs (models, iterations, A→C/B demo defaults): see `predictor/config.py`.

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
