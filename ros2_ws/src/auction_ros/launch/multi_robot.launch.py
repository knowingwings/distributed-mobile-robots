"""Launch N auction agents + the mission node on one machine.

    ros2 launch auction_ros multi_robot.launch.py
    ros2 launch auction_ros multi_robot.launch.py robots:=4 \
        mission_file:=/path/to/mission.yaml die_robot:=0 die_after:=6.0
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

POSITIONS = [(0.5, 0.5), (3.5, 0.5), (2.0, 3.5), (0.5, 3.5), (3.5, 3.5), (2.0, 0.5)]


def _setup(context):
    robots = int(LaunchConfiguration("robots").perform(context))
    mission_file = LaunchConfiguration("mission_file").perform(context)
    die_robot = int(LaunchConfiguration("die_robot").perform(context))
    die_after = float(LaunchConfiguration("die_after").perform(context))

    nodes = [
        Node(
            package="auction_ros",
            executable="mission_node",
            name="auction_mission",
            parameters=[{"mission_file": mission_file}],
            output="screen",
        )
    ]
    for i in range(robots):
        x, y = POSITIONS[i % len(POSITIONS)]
        nodes.append(
            Node(
                package="auction_ros",
                executable="agent_node",
                name=f"auction_agent_{i}",
                parameters=[
                    {
                        "robot_id": i,
                        "x": x,
                        "y": y,
                        "die_after": die_after if i == die_robot else 0.0,
                    }
                ],
                output="screen",
            )
        )
    return nodes


def generate_launch_description():
    default_mission = os.path.join(
        get_package_share_directory("auction_ros"), "config", "demo_mission.yaml"
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("robots", default_value="3"),
            DeclareLaunchArgument("mission_file", default_value=default_mission),
            DeclareLaunchArgument("die_robot", default_value="-1"),
            DeclareLaunchArgument("die_after", default_value="0.0"),
            OpaqueFunction(function=_setup),
        ]
    )
