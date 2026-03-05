# OpenStack Network Agents

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

A [snap](https://snapcraft.io/) that packages the networking agents and
utilities needed to run OpenStack on hosts with Open vSwitch (OVS) and OVN.
It is designed to be co-located with [MicroOVN](https://github.com/canonical/microovn)
and is part of the [Sunbeam](https://canonical-openstack.readthedocs-hosted.com/en/) project.

## What it does

| Capability | Description |
|---|---|
| **Provider-bridge management** | Creates OVS bridges, attaches physical NICs, and configures OVN physnet mappings for external network connectivity. |
| **NIC discovery** | Identifies candidate uplink interfaces, filtering out virtual devices and bond members. |
| **CLI** | Provides `setup-bridge`, `show-bridge-setup`, and `list-nics` subcommands for manual inspection and one-shot configuration. |

## Prerequisites

* Ubuntu 24.04 (Noble) or later
* [MicroOVN](https://github.com/canonical/microovn) installed and the
  `ovn-chassis` content interface connected

## Install

```bash
sudo snap install openstack-network-agents
```

## Configuration

The snap is configured through `snap set` keys and is typically driven by a
Juju subordinate charm. All keys live under the `network.*` namespace:

| Key | Default | Description |
|---|---|---|
| `network.bridge-mapping` | *(unset)* | Comma-separated `bridge:physnet:interface` triples. This is the **preferred** way to configure mappings. |
| `network.enable-chassis-as-gw` | `true` | Register this chassis as an OVN gateway router. |
| `network.external-bridge-address` | `0.0.0.0/0` | Static CIDR to assign to the bridge in localnet (single-node) mode. |
| `network.bridge` | `br-ex` | *(Deprecated)* Single bridge name. Use `network.bridge-mapping` instead. |
| `network.physnet` | `physnet1` | *(Deprecated)* Single physnet name. Use `network.bridge-mapping` instead. |
| `network.interface` | *(unset)* | *(Deprecated)* Single NIC name. Use `network.bridge-mapping` instead. |
| `logging.debug` | `false` | Enable debug logging for hooks and CLI. |

Example:

```bash
sudo snap set openstack-network-agents \
  network.bridge-mapping="br-ex:physnet1:enp6s0"
```

## CLI usage

The snap ships the `openstack-network-agents` command with several subcommands.

### list-nics

List candidate uplink NICs (physical, bond, and VLAN interfaces that are not
already claimed):

```bash
openstack-network-agents list-nics              # JSON (default)
openstack-network-agents list-nics -f table      # human-readable table
```

### setup-bridge

Apply the current snap configuration to create/update OVS bridges and physnet
mappings:

```bash
openstack-network-agents setup-bridge
```

### show-bridge-setup

Display the current OVS bridge-to-physnet mappings detected on the host:

```bash
openstack-network-agents show-bridge-setup
```

## Development

### Requirements

* Python 3.12
* [uv](https://github.com/astral-sh/uv) (used for dependency management and
  lock file)
* [tox](https://tox.wiki/) (test runner)

### Getting started

```bash
# Clone the repository
git clone https://github.com/canonical/snap-openstack-network-agents.git
cd snap-openstack-network-agents

# Run the unit tests
tox -e unit

# Lint & format check
tox -e pep8

# Type checking
tox -e mypy

# Auto-format code
tox -e fmt
```

### Building the snap

```bash
snapcraft
```

### Project layout

```
openstack_network_agents/
├── cli/            # Click-based CLI commands
├── core/           # Business logic (bridge management, NIC discovery, OVS client)
└── hooks/          # Snap install & configure hooks
snap/
└── snapcraft.yaml  # Snap packaging definition
tests/
└── unit/           # Unit tests
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository and create a feature branch.
2. Ensure `tox` passes (`unit`, `pep8`, `mypy`).
3. Open a pull request against `main`.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
