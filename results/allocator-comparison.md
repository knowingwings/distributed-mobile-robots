# Allocator comparison — repeated rounds vs SSI, and the cost of collaboration

**Run:** 2026-07-04 on terra (14 workers), commit `c1ffefc`.
**Data:** `results/bench_allocators.csv` (2,160 rows: 720 paired instances × 3 allocators; K ∈ {4,8,16,32} × robots ∈ {2,4,8} × loss ∈ {0,0.3} × delay ∈ {0,200 ms} × 15 reps, identical seeds across allocators) and `results/bench_collab.csv` (180 coordination-stack missions, collab fraction ∈ {0,0.2,0.4}). Regenerate with `python -m auction_core.validation.benchmark`; summarise with `python -m auction_core.validation.analyze`.

## Headline results

**1. Repeated rounds match SSI-makespan on solution quality and beat it at scale.**

Makespan / CPM-lower-bound ratio by task count:

| allocator | K=4 | K=8 | K=16 | K=32 |
|---|---|---|---|---|
| rounds | 1.963 | 2.030 | 1.999 | **1.834** |
| ssi-makespan | **1.905** | **1.998** | 2.062 | 2.013 |
| ssi-sumcost | 2.281 | 2.459 | 2.703 | 2.687 |

SSI edges ahead on small instances; repeated rounds win as K grows. The plausible mechanism: rounds re-auction event-driven as the DAG unlocks and robots free, so allocation decisions use *current* positions and workloads, while SSI commits everything up-front with append-only insertion and pays for stale decisions on long missions. Paired per-instance deltas (same seeds): rounds beat ssi-makespan by +4.1 s mean (+0.7 s median) and ssi-sumcost by +22.9 s mean over 720 pairs.

**2. The sum-cost bid rule is decisively wrong for makespan missions** — 20–35% worse ratios throughout. Consistent with the SSI literature's preference for BidMinMakespan when minimising completion time; kept in the harness as the cautionary baseline.

**3. Rounds are far more communication-robust under loss** (the space-relevant result):

| allocator | messages @ loss 0 | messages @ loss 0.3 |
|---|---|---|
| rounds | 1,689 | 5,352 (×3.2) |
| ssi (either rule) | 2,285 | 26,194 (×11.5) |

Every SSI item pays its own loss-scaled consensus window (K sequential agreements), while a round amortises one window across a whole batch of assignments. For disrupted links — the DTN/orbital trajectory — batch auctions win on communication by a factor of ~5 at 30% loss.

**4. Collaboration costs what it visibly costs.** Full coordination stack, mission makespan ratio and messages vs collaborative fraction:

| collab fraction | makespan/bound | messages |
|---|---|---|
| 0.0 | 2.41 | 8,963 |
| 0.2 | 3.05 | 11,478 |
| 0.4 | 3.82 | 13,862 |

Sources of overhead, in order: two robots occupied per collaborative task (the bound itself doesn't model pairing), recruitment latency (a second mini-auction), and one-collaboration-per-round framing (the deliberate serialisation that prevents mutual-leader livelock). These are honest prices, not bugs — but tightening the framing rule (e.g. allowing ⌊idle/2⌋ collaborations per round with reserved followers) is an obvious optimisation candidate.

## What the benchmark caught while being built

Worth recording because it validates the harness-first method: the collab suite found a **mutual-leader livelock** (two collaborative tasks framed together with two robots — each wins one, both lead, both wait for the other forever), and a **recruitment pre-emption race** (a coordinator announcement replacing an in-flight recruitment bid, leaving the leader paired with a robot that no longer knew it had bid). Both were specification-level design gaps, found by randomised system-level sweeps within minutes, fixed in `participant.py` (one-collab-per-round framing; non-pre-emptible recruitment bids + renewal-driven pairing acceptance).

## Caveats

- SSI uses append-only insertion; cheapest-insertion would improve its ratios (future work, likely narrows result 1 at small K).
- SSI has no in-mission failure recovery story here; the failure-robustness comparison is deliberately out of scope until it gets one (repeated rounds get recovery "for free" via leases).
- Makespan ratios are against a *lower bound* that ignores travel and pairing, so absolute values overstate the gap to true optimal; cross-allocator comparisons on identical instances are the meaningful quantity.
- The collab suite runs at zero loss/delay; collaborative behaviour under communication stress is covered qualitatively by `test_collaborative.py` (30% loss) but not swept quantitatively yet.
