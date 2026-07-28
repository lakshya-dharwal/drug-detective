#!/usr/bin/env python3
"""Run the pipeline against benchmark_dataset.json and report top-10 recall.

For each {disease, known_repurposed_drug} pair: run the pipeline for `disease`,
resolve `known_repurposed_drug` to a canonical ChEMBL ID (so brand/generic name
differences don't cause false negatives), and check whether that ChEMBL ID
appears in the top 10 ranked candidates.

Usage: python benchmark/evaluate_benchmark.py [--top-n 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.entity_resolver import resolve_drug  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

BENCHMARK_PATH = Path(__file__).parent / "benchmark_dataset.json"


def evaluate(top_n: int = 10) -> None:
    with BENCHMARK_PATH.open("r", encoding="utf-8") as f:
        benchmark = json.load(f)

    hits = 0
    results = []

    for case in benchmark:
        disease = case["disease"]
        known_drug = case["known_repurposed_drug"]

        pipeline_result = run_pipeline(disease)
        top_candidates = pipeline_result.ranked_candidates[:top_n]

        resolved = resolve_drug(known_drug)
        target_chembl_id = resolved.chembl_id if resolved else None

        found = False
        rank = None
        if target_chembl_id:
            for i, candidate in enumerate(top_candidates, start=1):
                if candidate.drug_chembl_id == target_chembl_id:
                    found = True
                    rank = i
                    break
        else:
            # Couldn't resolve the known drug at all - fall back to a loose name match.
            for i, candidate in enumerate(top_candidates, start=1):
                if candidate.drug_name.strip().lower() == known_drug.strip().lower():
                    found = True
                    rank = i
                    break

        if found:
            hits += 1

        results.append(
            {
                "disease": disease,
                "known_drug": known_drug,
                "resolved_chembl_id": target_chembl_id,
                "found_in_top_n": found,
                "rank": rank,
                "candidates_returned": len(pipeline_result.ranked_candidates),
                "status_message": pipeline_result.status_message,
            }
        )

        status = f"FOUND @ rank {rank}" if found else "NOT FOUND"
        print(f"[{status:14}] {disease:35} -> {known_drug}")

    total = len(benchmark)
    accuracy_pct = (hits / total * 100) if total else 0.0
    print(f"\n{hits}/{total} known drugs appeared in top {top_n} ({accuracy_pct:.1f}%)")

    report_path = Path(__file__).parent / "benchmark_results.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"top_n": top_n, "hits": hits, "total": total, "accuracy_pct": accuracy_pct, "results": results},
            f,
            indent=2,
        )
    print(f"Full results written to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()
    evaluate(top_n=args.top_n)
