#!/usr/bin/env python3
# Copyright 2023 Martin Kalcok
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm the service.

Refer to the following post for a quick-start guide that will help you
develop a new k8s charm using the Operator Framework:

https://discourse.charmhub.io/t/4208
"""

import logging
import os

from base64 import b64decode
from typing import Optional

import yaml
from ops.charm import CharmBase, InstallEvent, ConfigChangedEvent, RelationEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus, ModelError

from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]


class CharmInventoryCollectorCharm(CharmBase):
    """Charm the service."""

    COLLECTOR_SNAP = "software-inventory-collector"
    CONFIG_PATH = f"/var/snap/{COLLECTOR_SNAP}/current/collector.yaml"

    def __init__(self, *args):
        super().__init__(*args)
        self._snap_path: Optional[str] = None
        self._is_snap_path_cached = False

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.inventory_exporter_relation_changed, self._on_inventory_exporter_relation_changed)
        self.framework.observe(self.on.inventory_exporter_relation_departed, self._on_inventory_exporter_relation_changed)

    @property
    def snap_path(self) -> Optional[str]:
        """Get local path to exporter snap.

        If this charm has snap file for the exporter attached as a resource, this property returns
        path to the snap file. If the resource was not attached of the file is empty, this property
        returns None.
        """
        if not self._is_snap_path_cached:
            try:
                self._snap_path = str(self.model.resources.fetch("collector-snap"))
                # Don't return path to empty resource file
                if not os.path.getsize(self._snap_path) > 0:
                    self._snap_path = None
            except ModelError:
                self._snap_path = None
            finally:
                self._is_snap_path_cached = True

        return self._snap_path

    def _on_install(self, _: InstallEvent) -> None:
        if self.snap_path:
            snap.install_local(self.snap_path, dangerous=True)
        else:
            snap.ensure(snap_names=self.COLLECTOR_SNAP, state=str(snap.SnapState.Latest))

        self.assess_status()

    def _on_config_changed(self, _: ConfigChangedEvent) -> None:
        """Handle changed configuration.

        Change this example to suit your needs. If you don't need to handle config, you can remove
        this method.

        Learn more about config at https://juju.is/docs/sdk/config
        """
        self.render_config()
        self.assess_status()

    def _on_inventory_exporter_relation_changed(self, _: RelationEvent):
        self.render_config()
        self.assess_status()

    def render_config(self):
        config = {
            "settings": {},
            "juju_controller": {},
            "targets": [],
        }

        customer = self.config.get("customer")
        site = self.config.get("site")
        ca_cert = b64decode(self.config.get("juju_ca_cert")).decode("UTF-8")

        config["settings"]["collection_path"] = self.config.get("collection_path")
        config["settings"]["customer"] = customer
        config["settings"]["site"] = site
        config["juju_controller"]["endpoint"] = self.config.get("juju_endpoint")
        config["juju_controller"]["username"] = self.config.get("juju_username")
        config["juju_controller"]["password"]= self.config.get("juju_password")
        config["juju_controller"]["ca_cert"] = ca_cert

        for relation in self.model.relations.get("inventory-exporter"):
            for unit in relation.units:
                remote_data = relation.data[unit]
                endpoint = f"{remote_data.get('private-address')}:{remote_data.get('port')}"
                config["targets"].append({
                    "endpoint": endpoint,
                    "hostname": remote_data.get("hostname"),
                    "customer": customer,
                    "site": site,
                    "model": remote_data.get("model"),
                }
                )

        with open(self.CONFIG_PATH, "w", encoding="UTF-8") as conf_file:
            yaml.safe_dump(config, conf_file)

    def assess_status(self):
        self.unit.status = ActiveStatus("Unit ready.")


if __name__ == "__main__":  # pragma: nocover
    main(CharmInventoryCollectorCharm)
