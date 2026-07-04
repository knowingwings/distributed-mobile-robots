# Phase-1 factorial results — corrected auction core

**Run:** 2026-07-04, on terra (WSL2, 14 workers). 11,520 runs: full factorial
K ∈ {4,8,16,32} × delay ∈ {0,50,200,500} ms × loss ∈ {0,0.1,0.3,0.5} ×
ε ∈ {0.01,0.05,0.2,0.5}, 15 reps, fleet sizes n ∈ {2,4,8}.
Raw CSVs: `results/factorial_n{2,4,8}.csv` (not committed; regenerate with
`python -m auction_core.validation.experiments`). Summary via
`python -m auction_core.validation.analyze`.

## Headline

**Zero guarantee violations in 11,520 runs**: every auction round's total
benefit was within nε of the Hungarian optimum on the same frozen benefit
matrix, under every combination of delay, loss, task count, and fleet size.

## The dissertation's anomalies, re-tested on correct mechanics

| Original anomaly | This run |
|---|---|
| ε statistically inert (ANOVA p = 1.0) | Monotone both ways: mean round ticks 121 → 96 as ε goes 0.01 → 0.5; mean worst-round gap 0.0004 → 0.115. The speed/quality trade the theory predicts is back. |
| Optimality gap −0.72 (impossible) | Gap is measured in benefit space against a true optimum: always ≥ 0, always ≤ nε (max observed 0.115 « 4.0 = nε worst case). Makespan is reported against the CPM *bound* separately (mean ratio 1.98) with no optimality claim. |
| Delay swept but flat (parameter was never read) | Delay is in the message path: mean round ticks 34 → 225 as delay goes 0 → 500 ms, ~linear in delay as Prop 3.2's communication-round term predicts. |

Loss also acts as expected: ticks 27 → 197 as loss goes 0 → 0.5. Part of that
rise is the loss-aware quiescence window (sized so silent-termination
conflicts have probability < 1e-9 — see `suggested_quiescence`), which is the
honest cost of terminating safely over lossy links without acks.

## Fleet scaling (data the original project never had)

Round convergence degrades gracefully with fleet size at fixed conditions
(mean ticks 86 / 100 / 132 for n = 2 / 4 / 8, complete topology), and the nε
guarantee held at every size. Message totals are dominated by the quiescence
window rather than K (non-monotone in K: rounds get bigger but fewer robots
sit idle re-auctioning); a message-efficiency pass (gossip-on-change,
compressed tables) is an obvious phase-2/3 optimisation and should be
benchmarked against these baselines.

## Caveats

- Complete topology per round only (line/random topologies are exercised in
  the property tests, not this sweep).
- One tick = 50 ms nominal; tick-to-wall-clock mapping is a simulation
  convention, so cross-condition *ratios* are the meaningful quantities.
- Makespan/CPM ratio ≈ 2 is against a lower bound that is itself loose for
  dependency-heavy instances; it is a tracking metric, not a quality claim.
