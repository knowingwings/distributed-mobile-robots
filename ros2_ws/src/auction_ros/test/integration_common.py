"""Shared plumbing for the launch-based integration tests.

All auction topics are relative, so each test gets its own ROS namespace —
tests in the same pytest process (and even running concurrently) cannot
cross-talk, and late anti-entropy traffic from a finished test's dying
agents never leaks into the next test's monitor.
"""

from __future__ import annotations

import os
import time
import unittest

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node as LaunchNode
import launch_testing.actions

import auction_msgs.msg as m

BEST_EFFORT = QoSProfile(reliability=QoSReliabilityPolicy.BEST_EFFORT, depth=50)
POSITIONS = [(0.5, 0.5), (3.5, 0.5), (2.0, 3.5), (0.5, 3.5)]
TEST_MISSION_IDS = set(range(8))

AGENT_PARAMS = dict(
    heartbeat_interval=0.5,
    eta=3,
    epsilon=0.05,
    quiescence_rounds=8,
    round_timeout=6.0,
    tick_rate=10.0,
)


def mission_path() -> str:
    return os.path.join(
        get_package_share_directory("auction_ros"), "config", "test_mission.yaml"
    )


def make_nodes(ns: str, robots: int = 3, die_robot: int = -1, die_after: float = 0.0):
    nodes = [
        LaunchNode(
            package="auction_ros",
            executable="mission_node",
            name="auction_mission",
            namespace=ns,
            parameters=[{"mission_file": mission_path()}],
            output="screen",
        )
    ]
    for i in range(robots):
        x, y = POSITIONS[i % len(POSITIONS)]
        nodes.append(
            LaunchNode(
                package="auction_ros",
                executable="agent_node",
                name=f"auction_agent_{i}",
                namespace=ns,
                parameters=[
                    {
                        "robot_id": i,
                        "x": x,
                        "y": y,
                        "die_after": die_after if i == die_robot else 0.0,
                        **AGENT_PARAMS,
                    }
                ],
                output="screen",
            )
        )
    return nodes


def description(nodes) -> LaunchDescription:
    return LaunchDescription([*nodes, launch_testing.actions.ReadyToTest()])


class CompletionMonitor(Node):
    """Collects (task_id -> first completer) from <ns>/auction/completed."""

    def __init__(self, ns: str):
        super().__init__("completion_monitor", namespace=ns)
        self.completions: dict[int, int] = {}
        self.first_seen: dict[int, float] = {}
        self.create_subscription(
            m.TaskCompleted, "auction/completed", self._on_completed, BEST_EFFORT
        )

    def _on_completed(self, msg: m.TaskCompleted) -> None:
        self.completions.setdefault(msg.task_id, msg.by)
        self.first_seen.setdefault(msg.task_id, time.monotonic())


class IntegrationBase(unittest.TestCase):
    NS = "it"  # override per test file

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.monitor = CompletionMonitor(cls.NS)

    @classmethod
    def tearDownClass(cls):
        cls.monitor.destroy_node()
        rclpy.shutdown()

    def spin_until(self, predicate, timeout: float, what: str = "condition"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.monitor, timeout_sec=0.2)
            if predicate():
                return
        self.fail(
            f"timed out after {timeout}s waiting for {what}; "
            f"completions so far: {sorted(self.monitor.completions)}"
        )

    def wait_for_mission(self, expected_ids, timeout: float):
        self.spin_until(
            lambda: expected_ids <= set(self.monitor.completions),
            timeout,
            f"tasks {sorted(expected_ids)} to complete",
        )
