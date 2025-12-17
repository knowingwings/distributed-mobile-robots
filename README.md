# Distributed Mobile Robots: ROS2 Implementation

ROS2-based platform for researching decentralized coordination in multi-robot systems. This repository integrates validated distributed auction algorithms with custom rover hardware to enable research in autonomous task allocation and collaborative robotics.

## Overview

This project combines:
- **Validated coordination algorithms** from [decentralized-mobile-manipulator](https://github.com/knowingwings/decentralized-mobile-manipulator)
- **Custom rover platform** designed for multi-robot coordination research
- **Complete ROS2 stack** for navigation, control, and coordination
- **Gazebo simulation** to hardware deployment pipeline

The system enables research in decentralized multi-robot task allocation with real hardware validation.

## Project Status

Active Development

**Current milestones:**
- Repository structure created
- Algorithm validation complete (Python simulation)
- Rover mechanical design (completion: Dec 21, 2024)
- ROS2 navigation stack (planned: Week 1-2)
- Auction algorithm ROS2 port (planned: Week 3-4)
- Multi-robot coordination (planned: Week 5+)

## Repository Structure

```
distributed-mobile-robots/
├── ros2_ws/                        # ROS2 workspace
│   └── src/
│       ├── rover_description/      # URDF, meshes, robot models
│       ├── rover_bringup/          # Launch files and configurations
│       ├── rover_navigation/       # Nav2 integration
│       ├── rover_control/          # Low-level control
│       ├── auction_allocation/     # Distributed auction algorithm
│       ├── task_coordinator/       # Task management and dependencies
│       ├── consensus/              # Consensus protocol implementation
│       └── simulation_worlds/      # Gazebo worlds and scenarios
│
├── docker/                         # Docker configurations
├── docs/                           # Documentation
├── scripts/                        # Utility scripts
└── README.md                       # This file
```

## Quick Start

### Prerequisites

- Ubuntu 22.04 LTS
- ROS2 Humble
- Docker (optional, recommended)
- Python 3.10+
- Gazebo Garden

### Installation

**Option 1: Docker (Recommended)**

```bash
git clone https://github.com/knowingwings/distributed-mobile-robots.git
cd distributed-mobile-robots
docker-compose -f docker/docker-compose.yml up
```

**Option 2: Native Installation**

```bash
git clone https://github.com/knowingwings/distributed-mobile-robots.git
cd distributed-mobile-robots/ros2_ws
colcon build
source install/setup.bash
```

## Research Foundation

This implementation is based on validated algorithms from [decentralized-mobile-manipulator](https://github.com/knowingwings/decentralized-mobile-manipulator):

**Distributed Auction Algorithm:**
- Decentralized task allocation without central coordinator
- Mathematical guarantees: O(K² · b_max/ε) convergence, ≤ 2ε optimality gap
- GPU-accelerated bid calculation in simulation
- Robust failure recovery with time-weighted consensus

**Key Publications:**
- Zavlanos, M.M., et al. (2008). Distributed auction algorithm for the assignment problem
- BEng Dissertation: Decentralized Control Architecture for Dual Mobile Manipulators (First Class Honours)

## Development Roadmap

### Phase 1: Foundation (Week 1-2) - In Progress
- [x] Repository structure
- [x] Algorithm validation (Python simulation)
- [ ] Rover URDF and mechanical design
- [ ] Basic Gazebo simulation
- [ ] Single rover navigation stack

### Phase 2: ROS2 Algorithm Port (Week 3-4)
- [ ] Auction node implementation
- [ ] Task coordinator node
- [ ] Consensus protocol
- [ ] Message/service definitions

### Phase 3: Multi-Robot Coordination (Week 5-6)
- [ ] Dual-rover Gazebo world
- [ ] Multi-robot communication
- [ ] Coordinated task allocation
- [ ] Performance benchmarking

### Phase 4: Validation & Documentation (Week 7-8)
- [ ] Compare with Python simulation results
- [ ] Video demonstrations
- [ ] Comprehensive documentation

## Related Projects

- **[decentralized-mobile-manipulator](https://github.com/knowingwings/decentralized-mobile-manipulator)** - Python/PyTorch simulation and algorithm validation
- **[open-source-rover](https://github.com/knowingwings/open-source-rover)** - Rover mechanical design

## License

MIT License

## Author

**Thomas Le Huray**
- GitHub: @knowingwings
- LinkedIn: /in/tom-le-huray

MSc Robotics and Autonomous Systems @ University of Bath  
BEng Mechatronics (First Class Honours) @ University of Gloucestershire

---

Research platform for decentralized multi-robot coordination.
