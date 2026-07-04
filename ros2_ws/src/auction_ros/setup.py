from glob import glob

from setuptools import setup

package_name = "auction_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Tom Le Huray",
    maintainer_email="technical.wanderer@gmail.com",
    description="Thin ROS 2 wrapper hosting the auction_core coordination layer",
    license="MIT",
    entry_points={
        "console_scripts": [
            "agent_node = auction_ros.agent_node:main",
            "mission_node = auction_ros.mission_node:main",
        ],
    },
)
