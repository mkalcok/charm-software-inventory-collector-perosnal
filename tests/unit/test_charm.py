# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

from base64 import b64encode
from itertools import repeat
from unittest.mock import MagicMock, mock_open, patch

import charm
import pytest
from ops.model import ActiveStatus, BlockedStatus


@pytest.mark.parametrize(
    "resource_exists, resource_size, is_path_expected",
    [
        (False, 0, False),  # In case resource was not attached, return None
        (True, 0, False),  # In case the attached resource is empty file, return None
        (True, 10, True),  # If resource is attached and has size, return local path
    ],
)
def test_snap_path_property(resource_exists, resource_size, is_path_expected, harness):
    """Test that 'snap_path' property returns file path only when real resource is attached.

    If resource is not attached or if it's an empty file, this property should return None.
    """
    snap_name = "collector-snap"
    if resource_exists:
        # Generate some fake data for snap file if it's supposed to have some
        snap_data = "".join(list(repeat("0", resource_size)))
        harness.add_resource(snap_name, snap_data)

    expected_path = (
        str(harness.charm.model.resources.fetch(snap_name)) if is_path_expected else None
    )

    assert harness.charm.snap_path == expected_path


def test_snap_path_property_caching(harness, mocker):
    """Test that property 'snap_path' is cached after first call."""
    resource_fetch_mock = mocker.patch.object(harness.charm.model.resources, "fetch")
    resource_fetch_mock.side_effect = charm.ModelError()

    _ = harness.charm.snap_path
    _ = harness.charm.snap_path

    resource_fetch_mock.assert_called_once_with("collector-snap")


@pytest.mark.parametrize(
    "dry_run, expected_success",
    [
        (True, True),  # --dry-run passed
        (True, False),  # --dry-run failed
        (False, True),  # full run passed
        (False, False),  # full run failed
    ],
)
def test_run_collector(dry_run, expected_success, harness, mocker):
    """Test executing collector snap and check output/success."""
    check_output_mock = mocker.patch.object(charm.subprocess, "check_output")
    expected_cmd = [harness.charm.COLLECTOR_SNAP, "-c", harness.charm.CONFIG_PATH]
    if dry_run:
        expected_cmd.append("--dry-run")

    if not expected_success:
        error = charm.subprocess.CalledProcessError(1, cmd=expected_cmd, output="CMD failed")
        check_output_mock.side_effect = error
    else:
        check_output_mock.return_value = b"Command OK"

    cmd_result = harness.charm.run_collector(dry_run=dry_run)

    check_output_mock.assert_called_once_with(expected_cmd)
    assert cmd_result == expected_success


@pytest.mark.parametrize("local_snap", [True, False])
def test_on_install(local_snap, harness, mocker):
    """Test function that handles snap installation."""
    snap_path = "/path/to/snap" if local_snap else None
    harness.charm._snap_path = snap_path
    harness.charm._is_snap_path_cached = True
    assess_status_mock = mocker.patch.object(harness.charm, "assess_status")
    snap_mock = mocker.patch.object(charm, "snap")

    harness.charm._on_install(None)

    if local_snap:
        snap_mock.install_local.assert_called_once_with(snap_path, dangerous=True)
    else:
        expected_state = str(snap_mock.SnapState.Latest)
        snap_mock.ensure.assert_called_once_with(
            snap_names=harness.charm.COLLECTOR_SNAP, state=expected_state
        )

    assess_status_mock.assert_called_once()


def test_reconfigure_snap(harness, mocker):
    """Test function that handles changes in snap configuration."""
    render_config_mock = mocker.patch.object(harness.charm, "render_config")
    assess_status_mock = mocker.patch.object(harness.charm, "assess_status")

    harness.charm._reconfigure_snap(None)

    render_config_mock.assert_called_once()
    assess_status_mock.assert_called_once()


def test_render_config(harness, mocker):
    """Test function that renders snap configuration."""
    yaml_dump_mock = mocker.patch.object(charm.yaml, "safe_dump")
    # Charm config data
    site = "Testing Site"
    customer = "Test Customer"
    collection_path = "/tmp/output"
    juju_endpoint = "10.0.0.1:17070"
    juju_user = "admin"
    juju_pass = "pass"
    juju_ca_cert_raw = "--start cert--\nCERT DATA\n--end cert--"
    juju_ca_cert = b64encode(juju_ca_cert_raw.encode("UTF-8")).decode("ascii")

    # relation data
    exporter_ip = "10.0.0.5"
    exporter_port = "8765"
    exporter_hostname = "juju-exporter-0"
    model = "inventory-collector"

    # expected output
    expected_config = {
        "settings": {
            "collection_path": collection_path,
            "customer": customer,
            "site": site,
        },
        "juju_controller": {
            "endpoint": juju_endpoint,
            "username": juju_user,
            "password": juju_pass,
            "ca_cert": juju_ca_cert_raw,
        },
        "targets": [
            {
                "endpoint": f"{exporter_ip}:{exporter_port}",
                "hostname": exporter_hostname,
                "customer": customer,
                "site": site,
                "model": model,
            }
        ],
    }

    # Setup environment
    with harness.hooks_disabled():
        # Update charm config
        harness.update_config(
            {
                "site": site,
                "customer": customer,
                "collection_path": collection_path,
                "juju_ca_cert": juju_ca_cert,
                "juju_endpoint": juju_endpoint,
                "juju_username": juju_user,
                "juju_password": juju_pass,
            }
        )

        # Setup relation and data
        rel_name = "inventory-exporter"
        rel_app = "software-inventory-exporter"
        rel_unit = rel_app + "/0"
        rel_id = harness.add_relation(rel_name, rel_app)
        harness.add_relation_unit(rel_id, rel_unit)
        harness.update_relation_data(
            rel_id,
            rel_unit,
            {
                "private-address": exporter_ip,
                "port": exporter_port,
                "hostname": exporter_hostname,
                "model": model,
            },
        )

    # Trigger config generation
    open_file_function = mock_open()
    with patch("builtins.open", open_file_function) as file_open_mock:
        harness.charm.render_config()
        file_open_mock.assert_called_once_with(harness.charm.CONFIG_PATH, "w", encoding="UTF-8")

    yaml_dump_mock.assert_called_once_with(expected_config, open_file_function())


@pytest.mark.parametrize("collector_runs", [True, False])
def test_assess_status(collector_runs, harness, mocker):
    """Test function that sets the final status of the unit."""
    run_collector_mock = mocker.patch.object(
        harness.charm, "run_collector", return_value=collector_runs
    )

    harness.charm.assess_status()

    run_collector_mock.assert_called_once_with(dry_run=True)
    if collector_runs:
        assert isinstance(harness.charm.unit.status, ActiveStatus)
    else:
        assert isinstance(harness.charm.unit.status, BlockedStatus)


@pytest.mark.parametrize("action_success", [True, False])
def test_collect_action(action_success, harness, mocker):
    """Test executing 'collect' action."""
    run_collector_mock = mocker.patch.object(
        harness.charm, "run_collector", return_value=action_success
    )
    action_even = MagicMock()

    harness.charm._on_collect_action(action_even)

    if action_success:
        action_even.fail.assert_not_called()
    else:
        action_even.fail.assert_called_once_with("Collection failed. See logs for more info.")

    run_collector_mock.assert_called_once()
