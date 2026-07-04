"""Summarise factorial experiment CSVs into a markdown results note.

Usage:
    python -m auction_core.validation.analyze results/factorial_n*.csv > note.md
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict


def load(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                rows.append(
                    {
                        k: (v if k == "gap_within_bound" else float(v))
                        for k, v in row.items()
                    }
                )
    return rows


def by_factor(rows: list[dict], factor: str, metric: str) -> list[tuple[float, float, float]]:
    """[(level, mean, stdev)] of metric grouped by factor level."""
    groups: dict[float, list[float]] = defaultdict(list)
    for row in rows:
        groups[row[factor]].append(row[metric])
    return [
        (level, statistics.mean(vals), statistics.stdev(vals) if len(vals) > 1 else 0.0)
        for level, vals in sorted(groups.items())
    ]


def table(rows: list[dict], factor: str, metric: str, fmt: str = "{:.2f}") -> str:
    lines = [f"| {factor} | mean {metric} | sd |", "|---|---|---|"]
    for level, mean, sd in by_factor(rows, factor, metric):
        lines.append(f"| {level:g} | {fmt.format(mean)} | {fmt.format(sd)} |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    rows = load(argv)
    violations = [r for r in rows if r["gap_within_bound"] != "True"]
    print(f"# Factorial results ({len(rows)} runs)\n")
    print(f"**Guarantee violations: {len(violations)}**\n")

    print("## Epsilon effects (the signature that was absent before)\n")
    print("### Convergence speed\n")
    print(table(rows, "epsilon", "mean_round_ticks"), "\n")
    print("### Solution quality (worst per-round benefit gap vs Hungarian)\n")
    print(table(rows, "epsilon", "max_round_gap", "{:.4f}"), "\n")

    print("## Communication effects\n")
    print(table(rows, "delay_ms", "mean_round_ticks"), "\n")
    print(table(rows, "loss", "mean_round_ticks"), "\n")

    print("## Scale effects\n")
    print(table(rows, "K", "total_messages"), "\n")
    print(table(rows, "robots", "mean_round_ticks"), "\n")

    ratios = [r["makespan"] / r["cpm_lower_bound"] for r in rows if r["cpm_lower_bound"] > 0]
    print("## Makespan vs CPM lower bound\n")
    print(
        f"ratio mean {statistics.mean(ratios):.2f}, "
        f"median {statistics.median(ratios):.2f}, "
        f"p95 {sorted(ratios)[int(0.95 * len(ratios))]:.2f}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
