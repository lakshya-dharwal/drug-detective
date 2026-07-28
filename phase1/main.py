#!/usr/bin/env python3
"""CLI entry point: python main.py "glioblastoma" """

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from src.pipeline import run_pipeline  # noqa: E402 (must follow load_dotenv)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def print_result(result) -> None:
    print(f"\nDisease query: {result.disease_query}")

    if result.disease_resolved is None:
        print(f"  Could not resolve disease.\n  {result.status_message}\n")
        return

    print(f"Resolved to: {result.disease_resolved.name} ({result.disease_resolved.efo_id})")

    if result.status_message:
        print(f"\n{result.status_message}\n")
        return

    print(f"Associated genes found: {result.gene_count}")
    print(f"Ranked drug candidates: {len(result.ranked_candidates)}\n")

    if result.ranked_candidates:
        name_w = max(len(c.drug_name) for c in result.ranked_candidates) + 2
        name_w = max(name_w, len("DRUG") + 2)
        print(f"{'DRUG':<{name_w}}{'SCORE':>7}  {'PHASE':<12}TOP REASON")
        print("-" * (name_w + 7 + 2 + 12 + 40))
        for c in result.ranked_candidates[:20]:
            top_reason = c.explanation.split(".")[0]
            print(f"{c.drug_name:<{name_w}}{c.final_score:>7.2f}  {c.max_clinical_phase.value:<12}{top_reason}")
        print()

    if result.genes_without_drugs:
        print(f"Associated genes with no known drugs ({len(result.genes_without_drugs)}):")
        for g in result.genes_without_drugs[:15]:
            print(f"  - {g.hgnc_symbol} ({g.ensembl_id}), association score {g.association_score:.2f}")
        if len(result.genes_without_drugs) > 15:
            print(f"  ... and {len(result.genes_without_drugs) - 15} more")
        print()

    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  [{w.stage}] {w.message}")
        print()


def main() -> int:
    if len(sys.argv) != 2:
        print('Usage: python main.py "<disease name>"', file=sys.stderr)
        return 1

    disease_name = sys.argv[1]
    result = run_pipeline(disease_name)
    print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
