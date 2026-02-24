# SPDX-FileCopyrightText: 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import logging
import pprint

import click

from openstack_network_agents.core.bridge_datapath import (
    OVSCli,
    detect_current_mappings,
)
from openstack_network_agents.core.common import ovs_switch_socket
from openstack_network_agents.core.constants import (
    OVN_CHASSIS_PLUG,
    OVS_CLI_DEFAULT_TIMEOUT,
)
from openstack_network_agents.hooks.common import is_connected

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def show_bridge_setup(ctx: click.Context) -> None:
    """Show current network bridge setup for OpenStack agents."""
    snap = ctx.obj
    # Implementation of bridge setup goes here
    if not is_connected(OVN_CHASSIS_PLUG):
        logger.warning(f"{OVN_CHASSIS_PLUG} not connected; skipping configure.")
        return
    socket_path = ovs_switch_socket(snap)
    ovs_cli = OVSCli(socket_path, timeout=OVS_CLI_DEFAULT_TIMEOUT)
    current_mapping = detect_current_mappings(ovs_cli)
    print("Current bridge mappings detected:")
    pprint.pprint(current_mapping)
