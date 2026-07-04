"""Integration: the initial coordinator (robot 0) crashes mid-mission;
failover + lease recovery must still complete every task."""

import pytest

from integration_common import IntegrationBase, TEST_MISSION_IDS, description, make_nodes

NS = "it_ckill"


@pytest.mark.launch_test
def generate_test_description():
    return description(make_nodes(NS, robots=3, die_robot=0, die_after=4.0))


class TestCoordinatorKill(IntegrationBase):
    NS = NS

    def test_mission_survives_coordinator_death(self):
        self.wait_for_mission(TEST_MISSION_IDS, timeout=180.0)
        # The dead coordinator cannot have completed the bulk of the mission.
        by_survivors = [
            t for t, by in self.monitor.completions.items() if by != 0
        ]
        assert len(by_survivors) >= 6, self.monitor.completions
