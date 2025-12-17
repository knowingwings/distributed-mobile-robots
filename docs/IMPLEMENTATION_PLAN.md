# Implementation Plan: Distributed Mobile Robots

## Overview

This document outlines the step-by-step implementation plan for building the distributed mobile robots system. The plan integrates the rover platform with distributed coordination algorithms validated in the Python simulation.

## Timeline: 8-Week Implementation

### Week 1-2: Foundation & Single Rover

**Objectives:**
- Complete rover URDF (from mechanical design, due Dec 21)
- Set up basic Gazebo simulation
- Implement differential drive controller
- Get single rover navigating

**Tasks:**
1. Convert CAD to URDF with proper mass/inertia
2. Create Gazebo world file
3. Configure ros2_control for differential drive
4. Integrate Nav2 with basic costmaps
5. Test autonomous navigation to waypoints

**Deliverables:**
- Single rover spawns in Gazebo
- Teleoperation working
- Autonomous navigation functional
- Launch file for single rover

### Week 3-4: Algorithm Port to ROS2

**Objectives:**
- Port distributed auction algorithm from Python to ROS2
- Implement task coordinator
- Test with simulated tasks (no motion yet)

**Tasks:**
1. Create auction_allocation package
2. Define custom messages (Bid, Price, Task, etc.)
3. Implement AuctionNode (bid calculation, price updates)
4. Implement TaskCoordinatorNode
5. Port consensus protocol
6. Test convergence with static robots

**Deliverables:**
- auction_allocation ROS2 package
- Task allocation working (verified in logs)
- Unit tests for bid calculation
- Parameter file for algorithm tuning

### Week 5-6: Multi-Robot Coordination

**Objectives:**
- Dual-rover Gazebo simulation
- Integrate auction with navigation
- Coordinated task execution

**Tasks:**
1. Modify launch files for dual rovers
2. Create multi-robot Gazebo world
3. Implement task execution actions
4. Connect auction results to Nav2 goals
5. Add collision avoidance
6. Performance benchmarking

**Deliverables:**
- Dual rovers coordinate task allocation
- Robots navigate to allocated tasks
- Video demonstration
- Performance comparison with Python simulation

### Week 7-8: Validation & Polish

**Objectives:**
- Comprehensive testing
- Documentation
- Prepare for hardware deployment

**Tasks:**
1. Compare metrics with Python simulation
2. Failure recovery testing
3. Write comprehensive documentation
4. Create hardware deployment guide
5. Record demo videos for applications

**Deliverables:**
- Validation report
- Complete documentation
- Hardware setup guide
- Demo videos

## Technical Details

### ROS2 Package Structure

**rover_description:**
- URDF with accurate mass, inertia, collision geometry
- Gazebo plugins for sensors and motors
- RViz configuration

**rover_control:**
- Differential drive controller
- Joint state publisher
- Hardware abstraction layer

**rover_navigation:**
- Nav2 parameter files
- Costmap configurations
- Custom behavior tree (if needed)

**auction_allocation:**
- AuctionNode: bid calculation, price updates
- Messages: Bid.msg, Price.msg, Task.msg
- Services: AllocateTask.srv

**task_coordinator:**
- Task dependency graph
- Execution scheduling
- Status tracking

**consensus:**
- Time-weighted consensus protocol
- Heartbeat monitoring
- Failure detection

### Message Definitions

**Bid.msg:**
```
int32 robot_id
int32 task_id
float64 bid_value
int64 timestamp
```

**Price.msg:**
```
int32 task_id
float64 price
int32 winning_robot_id
```

**Task.msg:**
```
int32 id
geometry_msgs/Pose target_pose
float64 priority
int32[] dependencies
bool collaborative
```

### Key Parameters

From Python simulation (config/default.yaml):
- epsilon: 0.05
- alpha weights: [0.8, 0.3, 1.0, 1.2, 0.2]
- gamma: 0.5
- lambda: 0.1

## Demo Scenarios

### Scenario 1: Basic Task Allocation
- 2 rovers, 4 tasks
- No dependencies
- Test convergence time

### Scenario 2: Task Dependencies
- 2 rovers, 6 tasks
- Dependency chain: T1 → T2 → T3
- Verify topological ordering

### Scenario 3: Failure Recovery
- 2 rovers, 5 tasks
- Robot A fails mid-execution
- Verify task reallocation

## Success Criteria

**Phase 1 Complete:**
- Single rover navigates autonomously in Gazebo
- Can reach commanded waypoints reliably

**Phase 2 Complete:**
- Task allocation converges (verified in logs)
- Convergence time within 20% of Python simulation

**Phase 3 Complete:**
- Dual rovers coordinate and execute tasks
- No collisions during execution
- Video demonstration recorded

**Phase 4 Complete:**
- Documentation complete
- Performance metrics documented
- Ready for hardware deployment

## Hardware Deployment (Future)

**Requirements per rover:**
- Jetson Nano/Xavier NX
- Motor controllers
- Wheel encoders
- IMU
- (Optional) LiDAR for SLAM

**Setup:**
1. Flash Jetson with ROS2 Humble
2. Configure motor controller interfaces
3. Calibrate odometry
4. Test on hardware with same launch files

## Notes

- Prioritize getting single-robot working before multi-robot
- Use rqt_graph extensively for debugging
- Record rosbags for offline analysis
- Keep Docker image updated for reproducibility
