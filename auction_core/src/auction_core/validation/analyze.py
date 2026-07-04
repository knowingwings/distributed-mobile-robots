"""Summarise factorial experiment CSVs into a markdown results note.

Usage:
    python -m auction_core.validation.analyze results/factorial_n*.csv > note.md
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict


def _parse(value: str):
    try:
        return float(value)
    except ValueError:
        return value


def load(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                rows.append({k: _parse(v) for k, v in row.items()})
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


def by_two_factors(rows, f1, f2, metric):
    groups = defaultdict(list)
    for row in rows:
        groups[(row[f1], row[f2])].append(row[metric])
    return {k: statistics.mean(v) for k, v in sorted(groups.items())}


def benchmark_report(rows: list[dict]) -> int:
    allocator_rows = [r for r in rows if r["suite"] == "allocators"]
    collab_rows = [r for r in rows if r["suite"] == "collab"]
    print(f"# Allocator benchmark ({len(rows)} rows)\n")

    if allocator_rows:
        allocators = sorted({r["allocator"] for r in allocator_rows})
        print("## Makespan / CPM-bound ratio by K\n")
        cells = by_two_factors(allocator_rows, "allocator", "K", "ratio")
        ks = sorted({r["K"] for r in allocator_rows})
        print("| allocator | " + " | ".join(f"K={k:g}" for k in ks) + " |")
        print("|---" * (len(ks) + 1) + "|")
        for a in allocators:
            print(f"| {a} | " + " | ".join(f"{cells[(a, k)]:.3f}" for k in ks) + " |")
        print("\n## Messages by loss\n")
        cells = by_two_factors(allocator_rows, "allocator", "loss", "messages")
        losses = sorted({r["loss"] for r in allocator_rows})
        print("| allocator | " + " | ".join(f"loss={l:g}" for l in losses) + " |")
        print("|---" * (len(losses) + 1) + "|")
        for a in allocators:
            print(f"| {a} | " + " | ".join(f"{cells[(a, l)]:.0f}" for l in losses) + " |")
        # Paired deltas on identical instances.
        print("\n## Paired makespan deltas vs rounds (positive = rounds better)\n")
        keyed = defaultdict(dict)
        for r in allocator_rows:
            keyed[(r["seed"], r["K"], r["robots"], r["loss"], r["delay_ms"])][
                r["allocator"]
            ] = r["makespan"]
        for a in allocators:
            if a == "rounds":
                continue
            deltas = [
                v[a] - v["rounds"] for v in keyed.values() if a in v and "rounds" in v
            ]
            if deltas:
                print(
                    f"- {a}: mean {statistics.mean(deltas):+.2f}s, "
                    f"median {statistics.median(deltas):+.2f}s over {len(deltas)} pairs"
                )

    if collab_rows:
        print("\n## Coordination stack vs collaborative fraction\n")
        print(table(collab_rows, "collab_fraction", "ratio", "{:.3f}"), "\n")
        print(table(collab_rows, "collab_fraction", "messages", "{:.0f}"), "\n")
    return 0


def main(argv: list[str]) -> int:
    rows = load(argv)
    if rows and "allocator" in rows[0]:
        return benchmark_report(rows)
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
