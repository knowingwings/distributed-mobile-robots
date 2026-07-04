"""Integration: a task injected at runtime is allocated and completed."""

import time

import pytest
import rclpy

import auction_msgs.msg as m
from integration_common import (
    BEST_EFFORT,
    IntegrationBase,
    TEST_MISSION_IDS,
    description,
    make_nodes,
)

NS = "it_inject"


@pytest.mark.launch_test
def generate_test_description():
    return description(make_nodes(NS, robots=3))


class TestInjection(IntegrationBase):
    NS = NS

    def test_injected_task_completes(self):
        pub = self.monitor.create_publisher(
            m.TaskSpec, "auction/inject_task", BEST_EFFORT
        )
        spec = m.TaskSpec(
            id=99, position=[1.0, 3.0], duration=1.0,
            capabilities=[], prerequisites=[], required_robots=1,
        )
        # Publish repeatedly for a while (BEST_EFFORT + discovery races).
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            pub.publish(spec)
            rclpy.spin_once(self.monitor, timeout_sec=0.5)
        self.wait_for_mission(TEST_MISSION_IDS | {99}, timeout=150.0)
