"""Integration: a worker holding tasks crashes; leases expire and the
survivors re-run its work."""

import pytest

from integration_common import IntegrationBase, TEST_MISSION_IDS, description, make_nodes

NS = "it_wkill"


@pytest.mark.launch_test
def generate_test_description():
    return description(make_nodes(NS, robots=3, die_robot=2, die_after=3.0))


class TestWorkerKill(IntegrationBase):
    NS = NS

    def test_orphaned_tasks_recovered(self):
        self.wait_for_mission(TEST_MISSION_IDS, timeout=180.0)
