"""Integration: 3 agents complete the 8-task DAG mission."""

import pytest

from integration_common import IntegrationBase, TEST_MISSION_IDS, description, make_nodes

NS = "it_mission"


@pytest.mark.launch_test
def generate_test_description():
    return description(make_nodes(NS, robots=3))


class TestMissionCompletes(IntegrationBase):
    NS = NS

    def test_all_tasks_complete(self):
        self.wait_for_mission(TEST_MISSION_IDS, timeout=120.0)
