"""Mission node: loads a YAML mission and latches it on /auction/tasks.

Runtime injection: publish a TaskSpec on /auction/inject_task and the
mission node appends it and re-latches the extended TaskArray (agents add
unknown ids only, so re-publication is idempotent).

YAML schema:
    tasks:
      - id: 0
        position: [1.0, 1.0]
        duration: 4.0
        prerequisites: []      # optional
        capabilities: []       # optional
        required_robots: 1     # optional
"""

from __future__ import annotations

import yaml

import rclpy
from rclpy.node import Node

import auction_msgs.msg as m
from .agent_node import GOSSIP_QOS, MISSION_QOS


class MissionNode(Node):
    def __init__(self):
        super().__init__("auction_mission")
        mission_file = self.declare_parameter("mission_file", "").value
        self._tasks: list[m.TaskSpec] = []
        if mission_file:
            self._tasks = self._load(mission_file)
        self._pub = self.create_publisher(m.TaskArray, "auction/tasks", MISSION_QOS)
        self.create_subscription(
            m.TaskSpec, "auction/inject_task", self._on_inject, GOSSIP_QOS
        )
        self._latch()
        self.get_logger().info(
            f"mission loaded: {len(self._tasks)} tasks from {mission_file or '(none)'}"
        )

    def _load(self, path: str) -> list[m.TaskSpec]:
        with open(path) as fh:
            spec = yaml.safe_load(fh)
        tasks = []
        for entry in spec.get("tasks", []):
            tasks.append(
                m.TaskSpec(
                    id=int(entry["id"]),
                    position=[float(v) for v in entry.get("position", [])],
                    duration=float(entry.get("duration", 1.0)),
                    capabilities=[float(v) for v in entry.get("capabilities", [])],
                    prerequisites=[int(v) for v in entry.get("prerequisites", [])],
                    required_robots=int(entry.get("required_robots", 1)),
                )
            )
        return tasks

    def _latch(self) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        self._pub.publish(m.TaskArray(stamp=now, tasks=self._tasks))

    def _on_inject(self, spec: m.TaskSpec) -> None:
        if any(t.id == spec.id for t in self._tasks):
            self.get_logger().warning(f"duplicate injected task id {spec.id} ignored")
            return
        self._tasks.append(spec)
        self._latch()
        self.get_logger().info(f"task {spec.id} injected; mission now {len(self._tasks)} tasks")


def main(args=None):
    rclpy.init(args=args)
    node = MissionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
