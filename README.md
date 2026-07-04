# Distributed Mobile Robots

Platform for researching decentralised coordination in multi-robot systems: a
**platform-agnostic distributed auction core** (`auction_core`, pure Python,
zero ROS dependencies) with a ROS 2 wrapper and rover integration to follow.
Targets the [open-source-rover](https://github.com/knowingwings/open-source-rover)
platform, with extension toward communication-constrained extreme environments
(delay/disruption-tolerant coordination) as a long-term goal.

## Overview

The core reimplements the distributed auction algorithm of Zavlanos, Spesivtsev
& Pappas (2008) — an extension of Bertsekas' auction algorithm to networked
systems with only local communication — correcting the specification defects
found in the predecessor BEng-dissertation implementations (wrong price-update
rule, missing outbidding, stability-based termination; see the maths
evaluation in the project workspace).

Design principles:

- **Sans-I/O engine.** Each agent is a deterministic state machine
  (`handle_message`/`tick`); time and transport are injected. The same engine
  runs under pytest, a simulated lossy network, ROS 2, or store-and-forward.
- **Max-merge price propagation.** Price tables reconcile by entry-wise
  `max()` (max-price / max-index): associative, commutative, idempotent —
  message loss, duplication, and reordering cannot corrupt auction state.
- **Frozen benefits per round.** The auction solves the one-task-per-agent
  assignment problem it has guarantees for; all adaptivity (workload,
  distance, DAG availability) lives in the scheduling layer between rounds.

Honest guarantee inventory (per round, n agents, minimum bid increment ε):

- Convergence: O(Δ · n² · ⌈range(β)/ε⌉) iterations, Δ = network diameter
- Total benefit within **nε** of the optimal assignment (exact for integer
  benefits with ε < 1/n) — verified against the Hungarian algorithm by
  property-based tests under delay, loss, and multi-hop topologies
- Makespan across rounds is reported against the CPM lower bound; **no
  makespan-optimality claim is made** (none is inherited from the theory)

## Repository structure

```
distributed-mobile-robots/
├── auction_core/                   # platform-agnostic core
│   ├── src/auction_core/
│   │   ├── auction/                # Zavlanos Alg. 1 engine + price table
│   │   ├── scheduling/             # task DAG, CPM, benefit definition
│   │   ├── allocator/              # repeated frozen-β rounds (SSI later)
│   │   ├── liveness/               # heartbeat detection + task leases
│   │   ├── coordination/           # rotating-coordinator participant
│   │   └── validation/             # Hungarian reference, sim transport,
│   │                               #   round harness, system sim, experiments
│   ├── tests/                      # unit + hypothesis property tests
│   └── examples/demo.py
├── ros2_ws/src/
│   ├── auction_msgs/               # msg mirror of coordination messages
│   └── auction_ros/                # per-robot agent node, mission node,
│                                   #   launch files, integration tests
├── docker/                         # ROS 2 Humble dev container
└── scripts/terra-ci.sh             # heavy CI loop (build+test on terra)
```

## Quick start (auction core, no ROS required)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "auction_core[dev]"
pytest auction_core/tests
python auction_core/examples/demo.py
python -m auction_core.validation.experiments --quick --out results/smoke.csv
```

Requires Python ≥ 3.10 (ROS 2 Humble compatible).

## Quick start (ROS 2, in the dev container)

```bash
docker compose -f docker/compose.yml run --rm dev
# inside the container:
pip3 install -e auction_core
cd ros2_ws && . /opt/ros/humble/setup.sh
colcon build --symlink-install && . install/setup.sh
ros2 launch auction_ros multi_robot.launch.py            # 3 robots, demo mission
ros2 launch auction_ros multi_robot.launch.py robots:=4 die_robot:=0 die_after:=6.0
```

`scripts/terra-ci.sh` runs the whole build + test cycle (core tests in the
container, colcon build/test incl. the launch-based integration tests) on
terra, where heavy compute belongs.

## Roadmap

### Phase 1 — validated core (this branch)
- [x] Auction engine with enforced invariants (price monotonicity, γ ≥ ε)
- [x] Simulated transport: topology, delay, Bernoulli loss, partitions
- [x] Property-based verification against Hungarian ground truth
- [x] DAG/CPM scheduling layer + repeated-rounds allocator
- [x] Factorial experiments (K, delay, loss, ε; fleet sizes 2/4/8)

### Phase 2 — ROS 2 integration (this branch)
- [x] Heartbeat liveness + lease-based task ownership (App. B §6.1 spec)
- [x] Rotating-coordinator round orchestration, validated in simulation
      (coordinator failover, lease-driven recovery, 30% loss + delay)
- [x] `auction_msgs` + per-robot agent node + mission node
- [x] Recovery re-auction of orphaned tasks (lease expiry → ordinary round)
- [x] Multi-node integration tests: happy path, coordinator kill,
      worker kill, runtime task injection

### Phase 3 — research (this branch)
- [x] SSI allocator (min-makespan + sum-cost bid rules) behind the same
      interface, distributed winner selection with honest message accounting
- [x] Collaborative tasks end-to-end in sim: leader-follower recruitment,
      synchronised execution, leader/follower failure recovery
- [x] Head-to-head benchmark (see `results/allocator-comparison.md`):
      rounds match SSI on quality, win at scale and under loss (×5 fewer
      messages at 30% loss); collaboration overhead quantified

### Phase 4 — simulation & hardware
- [ ] Gazebo (Humble + Harmonic) world, Nav2 executor replacing the mock
- [ ] Collaborative execution over ROS
- [ ] Rover hardware integration

## Research foundation

- Zavlanos, M.M., Spesivtsev, L., Pappas, G.J. (2008). *A distributed auction
  algorithm for the assignment problem.* IEEE CDC, 1212–1217.
- Bertsekas, D.P. (1992). *Auction algorithms for network flow problems.*
  Computational Optimization and Applications 1, 7–66.
- BEng dissertation (Le Huray, 2025): problem formulation, dependency
  management, and failure-detection specs are adopted; the auction mechanics
  are corrected per the accompanying maths evaluation.

## License

MIT

## Author

**Thomas Le Huray** — GitHub [@knowingwings](https://github.com/knowingwings)

MSc Robotics and Autonomous Systems @ University of Bath
BEng Mechatronics (First Class Honours) @ University of Gloucestershire
