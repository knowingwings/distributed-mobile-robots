"""Per-robot agent node: thin ROS 2 host for CoordinationParticipant.

All coordination logic lives in auction_core (validated in simulation);
this node only adapts transport and time: DDS topics in/out, wall clock in,
plus a mock executor that "performs" a dispatched task by waiting
travel + duration seconds — the same interface the rover's navigation stack
replaces in phase 3.

QoS: coordination topics are BEST_EFFORT/KEEP_LAST(5) — loss tolerance
belongs to the algorithm (max-merge, rebroadcast, anti-entropy), not to DDS
retries. The mission topic is RELIABLE/TRANSIENT_LOCAL so late joiners get
the task list.

The `die_after` parameter hard-kills the process (os._exit) after N
seconds — crash injection for the failure integration tests; equivalent to
an external SIGKILL as far as the surviving team can observe.
"""

from __future__ import annotations

import os

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

from auction_core.coordination.messages import (
    Heartbeat,
    LeaseRenewal,
    RoundAnnouncement,
    RoundGossip,
    TaskCompleted,
    TaskInjected,
)
from auction_core.coordination.participant import CoordinationParticipant
from auction_core.scheduling.benefits import BenefitModel, RobotState, _distance

import auction_msgs.msg as m
from . import conversions as conv

GOSSIP_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    depth=5,
)
MISSION_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    depth=1,
)


class AgentNode(Node):
    def __init__(self):
        super().__init__("auction_agent")
        robot_id = self.declare_parameter("robot_id", 0).value
        x = self.declare_parameter("x", 0.0).value
        y = self.declare_parameter("y", 0.0).value
        speed = self.declare_parameter("speed", 1.0).value
        tick_rate = self.declare_parameter("tick_rate", 10.0).value
        die_after = self.declare_parameter("die_after", 0.0).value

        self.participant = CoordinationParticipant(
            RobotState(id=robot_id, position=(x, y), speed=speed),
            BenefitModel(),
            heartbeat_interval=self.declare_parameter("heartbeat_interval", 0.5).value,
            eta=self.declare_parameter("eta", 3).value,
            epsilon=self.declare_parameter("epsilon", 0.05).value,
            quiescence_rounds=self.declare_parameter("quiescence_rounds", 8).value,
            round_timeout=self.declare_parameter("round_timeout", 6.0).value,
        )

        self._pub = {
            Heartbeat: self.create_publisher(m.Heartbeat, "auction/heartbeat", GOSSIP_QOS),
            RoundAnnouncement: self.create_publisher(m.RoundAnnouncement, "auction/round", GOSSIP_QOS),
            RoundGossip: self.create_publisher(m.RoundGossip, "auction/gossip", GOSSIP_QOS),
            LeaseRenewal: self.create_publisher(m.LeaseRenewal, "auction/lease", GOSSIP_QOS),
            TaskCompleted: self.create_publisher(m.TaskCompleted, "auction/completed", GOSSIP_QOS),
        }
        self._to_msg = {
            Heartbeat: conv.heartbeat_to_msg,
            RoundAnnouncement: conv.announcement_to_msg,
            RoundGossip: conv.gossip_to_msg,
            LeaseRenewal: conv.lease_to_msg,
            TaskCompleted: conv.completed_to_msg,
        }

        self.create_subscription(
            m.Heartbeat, "auction/heartbeat",
            self._make_handler(conv.heartbeat_to_core), GOSSIP_QOS)
        self.create_subscription(
            m.RoundAnnouncement, "auction/round",
            self._make_handler(conv.announcement_to_core), GOSSIP_QOS)
        self.create_subscription(
            m.RoundGossip, "auction/gossip",
            self._make_handler(conv.gossip_to_core), GOSSIP_QOS)
        self.create_subscription(
            m.LeaseRenewal, "auction/lease",
            self._make_handler(conv.lease_to_core), GOSSIP_QOS)
        self.create_subscription(
            m.TaskCompleted, "auction/completed",
            self._make_handler(conv.completed_to_core), GOSSIP_QOS)
        self.create_subscription(
            m.TaskArray, "auction/tasks", self._on_task_array, MISSION_QOS)

        self._exec_timer = None
        self._exec_task = None
        self._mission_logged = False
        self.create_timer(1.0 / tick_rate, self._tick)
        if die_after > 0:
            self.create_timer(die_after, self._die)
        self.get_logger().info(f"agent {robot_id} up at ({x}, {y})")

    # ---------------------------------------------------------------- helpers

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def _publish(self, core_msg) -> None:
        kind = type(core_msg)
        self._pub[kind].publish(self._to_msg[kind](core_msg))

    def _make_handler(self, to_core):
        def handler(msg):
            self.participant.handle(to_core(msg), self._now())
        return handler

    def _on_task_array(self, msg: m.TaskArray) -> None:
        now = self._now()
        for spec in msg.tasks:
            if spec.id not in self.participant.tasks:
                self.participant.handle(
                    TaskInjected(conv.task_to_core(spec), now), now
                )

    # ------------------------------------------------------------------- tick

    def _tick(self) -> None:
        now = self._now()
        for core_msg in self.participant.tick(now):
            self._publish(core_msg)

        for task_id in self.participant.pop_aborts():
            self.get_logger().warning(f"aborting task {task_id} (lost lease)")
            self._cancel_execution()

        for task_id in self.participant.pop_dispatches():
            self._start_execution(task_id, now)

        if self.participant.mission_complete and not self._mission_logged:
            self._mission_logged = True
            self.get_logger().info("mission complete")

    # -------------------------------------------------------- mock execution

    def _start_execution(self, task_id, now: float) -> None:
        task = self.participant.tasks[task_id]
        travel = (
            _distance(self.participant.me.position, task.position)
            / self.participant.me.speed
            if self.participant.me.speed > 0
            else 0.0
        )
        wait = travel + task.duration
        self._exec_task = task_id
        self._exec_timer = self.create_timer(wait, self._finish_execution)
        self.get_logger().info(f"executing task {task_id} ({wait:.1f}s)")

    def _finish_execution(self) -> None:
        self._exec_timer.cancel()
        self.destroy_timer(self._exec_timer)
        self._exec_timer = None
        task_id, self._exec_task = self._exec_task, None
        for core_msg in self.participant.task_finished(task_id, self._now()):
            self._publish(core_msg)
        self.get_logger().info(f"finished task {task_id}")

    def _cancel_execution(self) -> None:
        if self._exec_timer is not None:
            self._exec_timer.cancel()
            self.destroy_timer(self._exec_timer)
            self._exec_timer = None
            self._exec_task = None

    def _die(self) -> None:
        self.get_logger().fatal("crash injection: dying now")
        os._exit(1)


def main(args=None):
    rclpy.init(args=args)
    node = AgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
