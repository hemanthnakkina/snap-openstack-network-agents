# SPDX-FileCopyrightText: 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import logging

import click

from openstack_network_agents.core.bridge_datapath import OVSCli
from openstack_network_agents.core.common import config_get, ovs_switch_socket
from openstack_network_agents.core.constants import (
    OVN_CHASSIS_PLUG,
    OVS_CLI_DEFAULT_TIMEOUT,
)
from openstack_network_agents.core.external_networking import (
    configure_ovn_external_networking,
)
from openstack_network_agents.hooks.common import is_connected

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def setup_bridge(ctx: click.Context) -> None:
    """Set up network bridges for OpenStack agents."""
    snap = ctx.obj
    # Implementation of bridge setup goes here
    if not is_connected(OVN_CHASSIS_PLUG):
        logger.warning(f"{OVN_CHASSIS_PLUG} not connected; skipping configure.")
        return
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
