# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing
"""Fixture for charm's unit tests."""

import ops.testing
import pytest
from charm import CharmSoftwareInventoryCollectorCharm

#
# @pytest.fixture(scope="session")
# def unit_hostname() -> str:
#     """Return statically defined units' hostname (IP)."""
#     return "10.0.0.1"


@pytest.fixture()
def harness() -> ops.testing.Harness[CharmSoftwareInventoryCollectorCharm]:
    """Return harness for PrometheusJujuExporterCharm."""
    ops.testing.SIMULATE_CAN_CONNECT = True
    # mocker.patch.object(PrometheusScrapeTarget, "get_hostname", return_value=unit_hostname)

    harness = ops.testing.Harness(CharmSoftwareInventoryCollectorCharm)
    harness.begin()
    yield harness

    harness.cleanup()
    ops.testing.SIMULATE_CAN_CONNECT = False
