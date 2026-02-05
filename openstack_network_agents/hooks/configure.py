# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import logging

from snaphelpers import Snap

from openstack_network_agents.core.bridge_datapath import OVSCli
from openstack_network_agents.core.common import config_get, ovs_switch_socket
from openstack_network_agents.core.constants import (
    OVN_CHASSIS_PLUG,
    OVS_CLI_DEFAULT_TIMEOUT,
)
from openstack_network_agents.core.external_networking import (
    configure_ovn_external_networking,
)
from openstack_network_agents.hooks.common import (
    is_connected,
    update_default_config,
)
from openstack_network_agents.hooks.log import setup_logging

logger = logging.getLogger(__name__)


def _configure_ovn_external_networking(snap: Snap) -> None:
    """Configure OVN external networking.

    :param snap: the snap reference
    :type snap: Snap
    :return: None
    """
    logger.info("Configuring OVN external networking.")
    config = config_get(snap)
    socket_path = ovs_switch_socket(snap)
    ovs_cli = OVSCli(socket_path, timeout=OVS_CLI_DEFAULT_TIMEOUT)
    configure_ovn_external_networking(
        config("network.bridge"),
        config("network.physnet"),
        config("network.interface"),
        config("network.bridge-mapping"),
        config("network.enable-chassis-as-gw") in ("true", True),
        ovs_cli,
    )


def hook(snap: Snap) -> None:
    """Configure hook for the OpenStack Network Agents snap."""
    setup_logging(snap.paths.common / "hooks.log")
    logger.info("Running configure hook for OpenStack Network Agents snap.")
    update_default_config(snap)

    if not is_connected(OVN_CHASSIS_PLUG):
        logger.warning(f"{OVN_CHASSIS_PLUG} not connected; skipping configure.")
        return
    _configure_ovn_external_networking(snap)
