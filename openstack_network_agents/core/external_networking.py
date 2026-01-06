# SPDX-FileCopyrightText: 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import logging
import time

from pyroute2 import IPRoute

from openstack_network_agents.core.bridge_datapath import (
    OVSCli,
    detect_current_mappings,
    resolve_bridge_mappings,
    resolve_ovs_changes,
    update_mappings_from_rename,
)

logger = logging.getLogger(__name__)


def _del_interface_from_bridge(
    ovs_cli: OVSCli, external_bridge: str, external_nic: str
) -> None:
    """Remove an interface from  a given bridge.

    :param bridge_name: Name of bridge.
    :param external_nic: Name of nic.
    """
    if external_nic in ovs_cli.list_bridge_interfaces(external_bridge):
        logging.warning(f"Removing interface {external_nic} from {external_bridge}")
        ovs_cli.del_port(external_bridge, external_nic)
    else:
        logging.warning(f"Interface {external_nic} not connected to {external_bridge}")


def _get_external_ports_on_bridge(ovs_cli: OVSCli, bridge: str) -> list:
    """Get microstack managed external port on bridge.

    :param ovs_cli: OVSCli instance.
    :param bridge: Name of bridge.
    """
    output = ovs_cli.find("Port", "external-ids:microstack-function=ext-port")
    name_idx = output["headings"].index("name")
    external_nics = [r[name_idx] for r in output["data"]]
    bridge_ifaces = ovs_cli.list_bridge_interfaces(bridge)
    return [i for i in bridge_ifaces if i in external_nics]


def _del_external_nics_from_bridge(ovs_cli: OVSCli, external_bridge: str) -> None:
    """Delete all microk8s managed external nics from bridge.

    :param bridge_name: Name of bridge.
    """
    for p in _get_external_ports_on_bridge(ovs_cli, external_bridge):
        _del_interface_from_bridge(ovs_cli, external_bridge, p)


def _add_interface_to_bridge(
    ovs_cli: OVSCli, external_bridge: str, external_nic: str
) -> None:
    """Add an interface to a given bridge.

    :param bridge_name: Name of bridge.
    :param external_nic: Name of nic.
    """
    if external_nic in ovs_cli.list_bridge_interfaces(external_bridge):
        logging.warning(
            f"Interface {external_nic} already connected to {external_bridge}"
        )
    else:
        logging.warning(f"Adding interface {external_nic} to {external_bridge}")
        ovs_cli.add_port(
            external_bridge,
            external_nic,
            external_ids={"microstack-function": "ext-port"},
        )


def get_machine_id() -> str:
    """Retrieve the machine-id of the system.

    :return: the machine-id string
    :rtype: str
    """
    with open("/etc/machine-id", "r") as f:
        return f.read().strip()


def _wait_for_interface(interface: str) -> None:
    """Wait for the interface to be created.

    :param interface: Name of the interface.
    :type interface: str
    :return: None
    """
    logging.debug(f"Waiting for {interface} to be created")
    ipr = IPRoute()
    start = time.monotonic()
    while not ipr.link_lookup(ifname=interface):  # type: ignore[attr-defined]
        if time.monotonic() - start > 30:
            raise TimeoutError(f"Timed out waiting for {interface} to be created")
        logging.debug(f"{interface} not found, waiting...")
        time.sleep(1)


def _ensure_single_nic_on_bridge(
    ovs_cli: OVSCli, external_bridge: str, external_nic: str
) -> None:
    """Ensure nic is attached to bridge and no other microk8s managed nics.

    :param bridge_name: Name of bridge.
    :param external_nic: Name of nic.
    """
    external_ports = _get_external_ports_on_bridge(ovs_cli, external_bridge)
    if external_nic in external_ports:
        logging.debug(f"{external_nic} already attached to {external_bridge}")
    else:
        _add_interface_to_bridge(ovs_cli, external_bridge, external_nic)
    for p in external_ports:
        if p != external_nic:
            logging.debug(
                f"Removing additional external port {p} from {external_bridge}"
            )
            _del_interface_from_bridge(ovs_cli, external_bridge, p)


def _ensure_link_up(interface: str):
    """Ensure link status is up for an interface.

    :param: interface: network interface to set link up
    :type interface: str
    """
    ipr = IPRoute()
    links = ipr.link_lookup(ifname=interface)  # type: ignore[attr-defined]
    if not links:
        logging.warning(f"Interface {interface} not found when ensuring link up")
        return
    dev = links[0]
    ipr.link("set", index=dev, state="up")  # type: ignore[attr-defined]


def _enable_chassis_as_gateway(ovs_cli: OVSCli):
    """Enable OVS as an external chassis gateway."""
    logging.info("Enabling OVS as external gateway")
    ovs_cli.set(
        "open",
        ".",
        "external_ids",
        {"ovn-cms-options": "enable-chassis-as-gw"},
    )


def _disable_chassis_as_gateway(ovs_cli: OVSCli):
    """Disable OVS as an external chassis gateway."""
    logging.info("Disabling OVS as external gateway")
    ovs_cli.remove("open", ".", "external_ids", "ovn-cms-options")


def configure_ovn_external_networking(
    bridge: str,
    physnet: str,
    interface: str,
    bridge_mapping: str,
    enable_chassis_as_gw: bool,
    ovs_cli: OVSCli,
) -> None:
    """Configure OVN external networking.

    :param bridge: network.bridge configuration
    :param physnet: network.physnet configuration
    :param interface: network.interface configuration
    :param bridge_mapping: network.bridge-mapping configuration
    :param enable_chassis_as_gw: network.enable-chassis-as-gw configuration (boolean)
    :param ovs_cli: OVS CLI interface
    :return: None
    """
    logger.info("Configuring OVN external networking.")

    mappings = resolve_bridge_mappings(
        bridge,
        physnet,
        interface,
        bridge_mapping,
    )
    current_mappings = detect_current_mappings(ovs_cli)

    changes = resolve_ovs_changes(current_mappings, mappings)
    logging.debug("OVS external networking changes: %s", changes)

    mappings = update_mappings_from_rename(mappings, changes["renamed_bridges"])

    for bridge, change in changes["interface_changes"].items():
        for iface in change["removed"]:
            logging.info(f"Removing interface {iface} from bridge {bridge}")
            _del_interface_from_bridge(ovs_cli, bridge, iface)
            # Adding interfaces is handled later.

    for bridge in changes["removed_bridges"]:
        logging.info(f"Removing ovs bridge {bridge}")
        ovs_cli.del_bridge(bridge)

    for bridge in changes["added_bridges"]:
        logging.info(f"Adding ovs bridge {bridge}")
        ovs_cli.add_bridge(
            bridge,
            "system",
            "protocols=OpenFlow13,OpenFlow15",
        )
    ovs_cli.set(
        "open",
        ".",
        "external_ids",
        {
            "ovn-bridge-mappings": ",".join(
                mapping.physnet_bridge_pair() for mapping in mappings
            )
        },
    )

    for mapping in mappings:
        _wait_for_interface(mapping.bridge)

    for mapping in mappings:
        logging.info(f"Resetting external bridge {mapping.bridge} configuration")
        if mapping.interface:
            logging.info(f"Adding {mapping.interface} to {mapping.bridge}")
            _ensure_single_nic_on_bridge(ovs_cli, mapping.bridge, mapping.interface)
            _ensure_link_up(mapping.interface)
        else:
            logging.info(f"Removing nics from {mapping.bridge}")
            _del_external_nics_from_bridge(ovs_cli, mapping.bridge)
    machine_id = get_machine_id()

    ovs_cli.set(
        "open",
        ".",
        "external_ids",
        {
            "ovn-chassis-mac-mappings": ",".join(
                mapping.physnet_mac_pair(machine_id) for mapping in mappings
            )
        },
    )

    if enable_chassis_as_gw:
        _enable_chassis_as_gateway(ovs_cli)
    else:
        _disable_chassis_as_gateway(ovs_cli)
