# Ayurvedic Predictive Model (agentic, evidence-verified)

Standalone project — **independent of Herbenzo / APEX**. Given a symptom or
problem, it proposes an Ayurvedic formulation (formula + formulation + delivery
system) and **substantiates every claim against live PubMed evidence**, or
honestly returns *insufficient evidence* when the evidence is not there.

## Why this design
It fixes the two failure modes of the old fine-tuned-RAG approach:
- **No fabricated/over-stretched citations** — every claim is checked against the
  article's own abstract, with a supporting quote, and graded by evidence level.
- **Honest refusal** — if nothing substantiates a claim after up to
  `MAX_ITERATIONS` *distinct* search strategies, it says so instead of guessing.

## Architecture → code map
| Stage | File |
|-------|------|
| 1. Dual interpretation (modern + Ayurvedic) | `agents.interpret` |
| 2. Knowledge-graph candidate generation | `knowledge_graph.py` |
| 3. Agentic evidence loop (retrieve → verify → escalate) | `agents.evidence_loop` |
| 3a. Retrieval + escalation ladder | `agents.escalated_query`, `connectors/pubmed.py` |
| 3b. Verification (claim support + grading) | `agents.verify_claim_against_article` |
| 4. Justification + chemistry grounding | `pipeline.predict`, `connectors/pubchem.py` |
| 5. Synthesis → recommendation OR refusal | `pipeline.predict` |
| Cross-cutting: audit trail | `audit_trail` in every result |

## Setup
```bash
pip install -r predictor/requirements.txt
# .env needs GEMINI_API_KEY (already present).
# Optional: ANTHROPIC_API_KEY + VERIFIER_MODEL=claude-... for cross-model verification.
```

## Run
```bash
# CLI
python -m predictor.cli "burning acidity and heartburn"
python -m predictor.cli "dry cough with phlegm" --json

# API
uvicorn predictor.api:app --reload --port 8000
# POST /predict {"query": "..."}   GET /health
```

## What is real vs. stubbed (MVP honesty)
- **Real & live:** PubMed (E-utilities) and PubChem (PUG-REST) connectors;
  Gemini interpretation + verification; bounded escalation loop; audit trail.
- **Seed-only (extend for production):** the knowledge graph in
  `knowledge_graph.py` covers 4 conditions / 4 classical formulas. Replace with
  the full Ayurvedic Pharmacopoeia + PubChem target links (Neo4j or similar).
- **Single-candidate:** the pipeline evaluates the top candidate per condition.
  Extend `pipeline.predict` to rank multiple candidates by evidence grade.

## Next steps
1. Cross-model verifier (add Anthropic key) to remove generator/verifier correlation.
2. Multi-candidate ranking + herb–drug interaction safety stage.
3. The non-circular evaluation harness (formulary recall, OOD/refusal, citation integrity).
