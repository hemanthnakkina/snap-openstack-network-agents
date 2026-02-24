# OpenStack Network Agents (snap)

This snap provides helpers for Sunbeam **network-role** nodes. It is designed to be co-located with `microovn`.

## Features

- **Fetch NICs**: List network interfaces available for OVS/OVN.
- **Configure OVS Bridge**: Configure bridge mappings, MAC chassis binding, and other OVS settings.

## Install

```bash
sudo snap install openstack-network-agents
```

## Usage

The snap exposes the `openstack-network-agents` command with several subcommands:

### List NICs

List candidate NICs for OVS/OVN use:

```bash
openstack-network-agents list-nics
```

### Configure Bridge

Configure the provider bridge and physnet mapping based on snap configuration:

```bash
sudo snap set openstack-network-agents \
  network.bridge-mapping=br-ex:physnet1:enp6s0

```

### Show Bridge Setup

Display the current bridge configuration:

```bash
openstack-network-agents show-bridge-setup
```
