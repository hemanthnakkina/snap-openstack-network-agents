# SPDX-FileCopyrightText: 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import errno
import ipaddress
import logging
import re
import subprocess
import time

from pyroute2 import IPRoute
from pyroute2.netlink.exceptions import NetlinkError

from openstack_network_agents.core.bridge_datapath import (
    OVSCli,
    detect_current_mappings,
    resolve_bridge_mappings,
    resolve_ovs_changes,
    update_mappings_from_rename,
)
from openstack_network_agents.hooks.common import IPVANYNETWORK_UNSET

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


def _add_ip_to_interface(interface: str, cidr: str) -> None:
    """Add IP to interface and set link to up.

    Deletes any existing IPs on the interface and set IP
    of the interface to cidr.

    :param interface: interface name
    :type interface: str
    :param cidr: network address
    :type cidr: str
    :return: None
    """
    logging.debug(f"Adding  ip {cidr} to {interface}")
    ipr = IPRoute()
    dev = ipr.link_lookup(ifname=interface)[0]  # type: ignore[attr-defined]
    ip_mask = cidr.split("/")
    try:
        ipr.addr("add", index=dev, address=ip_mask[0], mask=int(ip_mask[1]))  # type: ignore[attr-defined]
    except NetlinkError as e:
        if e.code != errno.EEXIST:
            raise e

    ipr.link("set", index=dev, state="up")  # type: ignore[attr-defined]


def _add_iptable_postrouting_rule(cidr: str, comment: str) -> None:
    """Add postrouting iptable rule.

    Add new postiprouting iptable rule, if it does not exist, to allow traffic
    for cidr network.
    """
    executable = "iptables-legacy"
    rule_def = [
        "POSTROUTING",
        "-w",
        "-t",
        "nat",
        "-s",
        cidr,
        "-j",
        "MASQUERADE",
        "-m",
        "comment",
        "--comment",
        comment,
    ]
    found = False
    try:
        cmd = [executable, "--check"]
        cmd.extend(rule_def)
        logging.debug(cmd)
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        # --check has an RC of 1 if the rule does not exist
        if e.returncode == 1 and re.search(
            r"No.*match by that name", e.stderr.decode()
        ):
            logging.debug(f"Postrouting iptable rule for {cidr} missing")
            found = False
        else:
            logging.warning(f"Failed to lookup postrouting iptable rule for {cidr}")
    else:
        # If not exception was raised then the rule exists.
        logging.debug(f"Found existing postrouting rule for {cidr}")
        found = True
    if not found:
        logging.debug(f"Adding postrouting iptable rule for {cidr}")
        cmd = [executable, "--append"]
        cmd.extend(rule_def)
        logging.debug(cmd)
        subprocess.check_call(cmd)


def _delete_iptable_postrouting_rule(comment: str) -> None:
    """Delete postrouting iptable rules based on comment."""
    logging.debug("Resetting iptable rules added by openstack-hypervisor")
    if not comment:
        return

    try:
        cmd = [
            "iptables-legacy",
            "-t",
            "nat",
            "-n",
            "-v",
            "-L",
            "POSTROUTING",
            "--line-numbers",
        ]
        process = subprocess.run(cmd, capture_output=True, text=True, check=True)
        iptable_rules = process.stdout.strip()

        line_numbers = [
            line.split(" ")[0] for line in iptable_rules.split("\n") if comment in line
        ]

        # Delete line numbers in descending order
        # If a lower numbered line number is deleted, iptables
        # changes lines numbers of high numbered rules.
        line_numbers.sort(reverse=True)
        for number in line_numbers:
            delete_rule_cmd = [
                "iptables-legacy",
                "-t",
                "nat",
                "-D",
                "POSTROUTING",
                number,
            ]
            logging.debug(f"Deleting iptable rule: {delete_rule_cmd}")
            subprocess.check_call(delete_rule_cmd)
    except subprocess.CalledProcessError as e:
        logging.info(f"Error in deletion of IPtable rule: {e.stderr}")


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


def configure_ovn_encap_ip(
    ip_address: str,
    ovs_cli: OVSCli,
) -> None:
    """Configure OVN encapsulation IP.

    :param ip_address: IP address to use for OVN encapsulation.
    :param ovs_cli: OVS CLI interface.
    :return: None
    """
    if not ip_address:
        logger.info("OVN encap IP not configured, skipping.")
        return
    logger.info("Configuring OVN encap IP: %s", ip_address)
    ovs_cli.set(
        "open",
        ".",
        "external_ids",
        {
            "ovn-encap-type": "geneve",
            "ovn-encap-ip": ip_address,
        },
    )


def configure_ovn_external_networking(
    bridge: str,
    physnet: str,
    interface: str,
    bridge_mapping: str,
    enable_chassis_as_gw: bool,
    external_bridge_address: str,
    ovs_cli: OVSCli,
) -> None:
    """Configure OVN external networking.

    :param bridge: network.bridge configuration
    :param physnet: network.physnet configuration
    :param interface: network.interface configuration
    :param bridge_mapping: network.bridge-mapping configuration
    :param enable_chassis_as_gw: network.enable-chassis-as-gw configuration (boolean)
    :param external_bridge_address: network.external-bridge-address configuration
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
    if not mappings:
        logging.info(
            "No valid bridge mappings found; skipping external network configuration."
        )
        return
    current_mappings = detect_current_mappings(ovs_cli)

    changes = resolve_ovs_changes(current_mappings, mappings)
    logging.debug("OVS external networking changes: %s", changes)

    mappings = update_mappings_from_rename(mappings, changes["renamed_bridges"])

    if len(mappings) > 1 and external_bridge_address != IPVANYNETWORK_UNSET:
        logging.warning(
            "External bridge address configuration is supported only for localnet (i.e. no external nics)."
        )
        return

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

    comment = "openstack-network-agents external network rule"
    if len(mappings) == 1 and external_bridge_address != IPVANYNETWORK_UNSET:
        # We only support localnet mode for a single virtual physnet
        mapping = mappings[0]
        logging.info(f"configuring external bridge {mapping.bridge}")
        _add_ip_to_interface(mapping.bridge, external_bridge_address)
        external_network = ipaddress.ip_interface(external_bridge_address).network
        _add_iptable_postrouting_rule(str(external_network), comment)
        # This is always gateway as single node only with localnet
        _enable_chassis_as_gateway(ovs_cli)
        return

    # We're in external net mode
    _delete_iptable_postrouting_rule(comment)

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
