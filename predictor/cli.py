"""Command-line runner for a single prediction.

Usage:
    python -m predictor.cli "dry cough with phlegm for a week"
    python -m predictor.cli "acidity and heartburn" --json
"""
from __future__ import annotations

import argparse
import json
import sys

from . import pipeline, config


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ayurvedic predictive model")
    ap.add_argument("query", help="symptom or problem statement")
    ap.add_argument("--json", action="store_true", help="print full JSON result")
    args = ap.parse_args(argv)

    result = pipeline.predict(args.query)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    m = result["models"]
    indep = "cross-provider" if m["cross_provider"] else ("cross-model" if m["cross_model"] else "SAME model")
    print(f"\nInput:  {result['input']}")
    print(f"Status: {result['status'].upper()}   (citations: {result['n_citations']})")
    print(f"Models: generator={m['generator']}  verifier={m['verifier']}  [{indep}]")
    if not config.llm_available():
        print("  [warning] no LLM key found — interpretation/verification ran in degraded mode")

    if result["status"] == "recommendation":
        o = result["outcome"]
        print(f"\nRecommended: {o['formula']}  ({o['formulation']})")
        print(f"Delivery:    {o['delivery_system']}")
        print(f"Ayurvedic:   {o['ayurvedic_frame']}")
        print(f"Evidence grade (overall): {o['overall_evidence_grade']}")
        print("\nSubstantiated claims:")
        for c in o["substantiated_claims"]:
            print(f"  • {c['claim']}  [{c['evidence_grade']}]")
            for cit in c["citations"][:3]:
                print(f"      - PMID {cit['pmid']} ({cit['year']}, {cit['evidence_level']}): {cit['url']}")
                if cit["support_quote"]:
                    print(f"        “{cit['support_quote'][:160]}”")
        if o["unsubstantiated_claims"]:
            print("\nCould NOT substantiate:")
            for c in o["unsubstantiated_claims"]:
                print(f"  • {c}")
    else:
        print(f"\nNo recommendation. {result.get('note', '')}")

    print(f"\n{result['disclaimer']}")
    print(f"(audit trail: {len(result['audit_trail'])} events)\n")


if __name__ == "__main__":
    sys.exit(main())
