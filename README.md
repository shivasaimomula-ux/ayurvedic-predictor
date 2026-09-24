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
- **Web UI:** http://127.0.0.1:8000 (polls `POST /jobs/predict` progress)
- **API docs:** http://127.0.0.1:8000/docs
- **CLI:** `python3 -m predictor.cli "constant stress and can't sleep"`

### Async jobs (Task T18 / Finding #20)
Long runs should use the job API so A’s UI (and F/glue) can poll without holding
one HTTP request for minutes:

```bash
# submit
curl -s -X POST http://127.0.0.1:8000/jobs/predict \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: optional-retry-key' \
  -d '{"query":"constant stress and can'\''t sleep"}'
# → 202 {"job_id":"…","status":"queued","poll_url":"/jobs/…","progress":{…}}

# poll
curl -s http://127.0.0.1:8000/jobs/<job_id>
# → progress.stage / progress.percent / result when succeeded
```

`POST /predict` remains **synchronous** for backward compatibility (existing
glue / F handoff). Prefer jobs for new callers. Budgets:
`PREDICT_JOB_TIMEOUT_S` (default 540), `PREDICT_MAX_CONCURRENT_JOBS` (default 2).

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

**Verifier cost order (Task T15 / Finding #11):** `NVIDIA (NIM) > Gemini` (Claude escalate opt-in)

1. **Default volume path:** local LLM verify (NIM Ultra → Gemini). Blue Adj on
   `:8011` is off by default (`ADJUDICATION_PREFERRED=0`) because Adj's first
   path is lexical and skips the LLM verifier.
2. Set `ADJUDICATION_PREFERRED=1` to prefer blue when reachable; else same local cascade.
3. Claude (`ESCALATE_MODEL`) only when `A_CLAUDE_ESCALATE=1` — never the default volume verifier.
4. `A_FORCE_AI_PROPOSE=1` (default) skips curated KG so chips and novel queries both run propose LLM.

| Var | Role |
|-----|------|
| `GEMINI_API_KEY` | Generator + cheap Gemini verifier |
| `NVIDIA_API_KEY` | NIM Ultra verifier (preferred when set) |
| `A_FORCE_AI_PROPOSE` | Default `1` — always run propose LLM |
| `ADJUDICATION_PREFERRED` | Default `0` — local LLM verify (set `1` for blue Adj) |
| `ANTHROPIC_API_KEY` | Optional Claude escalate only |
| `ADJUDICATION_URL` | Blue service (default `http://127.0.0.1:8011`) |
| `HERBENZO_PUBMED_CACHE_DIR` | Shared PMID disk cache with B / adjudication (Task T16) |
| `HERBENZO_PUBMED_CACHE_TTL_S` | Cache freshness window (default 30 days) |

Other knobs (models, iterations, A→C/B demo defaults): see `predictor/config.py`.

## Shared PubMed cache (Task T16)

A’s PubMed connector is **read-through** against `herbenzo-pubmed-cache`
(same on-disk layout as Stage B; Desktop path
`~/Desktop/herbenzo-pubmed-cache`). Set the env vars above to the **same absolute
directory** used by B and adjudication to avoid duplicate NCBI EFetch spend.
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
