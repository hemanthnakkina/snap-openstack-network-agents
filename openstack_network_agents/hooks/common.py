# SPDX-FileCopyrightText: 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import logging
import subprocess

from snaphelpers import Snap

logger = logging.getLogger(__name__)

UNSET = ""
IPVANYNETWORK_UNSET = "0.0.0.0/0"
DEFAULT_CONFIG = {
    "logging.debug": "false",
    # Deprecated
    "network.interface": UNSET,
    # Deprecated
    "network.bridge": "br-ex",
    # Deprecated
    "network.physnet": "physnet1",
    "network.bridge-mapping": UNSET,
    "network.ip-address": UNSET,
    "network.enable-chassis-as-gw": "true",
    # Only useful for local network (no remote interface)
    "network.external-bridge-address": IPVANYNETWORK_UNSET,
}


def update_default_config(snap: Snap) -> None:
    """Add any missing default configuration keys.

    :param snap: the snap reference
    :type snap: Snap
    :return: None
    """
    option_keys = set(k.split(".")[0] for k in DEFAULT_CONFIG.keys())
    current_options = snap.config.get_options(*option_keys)
    missing_options = {}
    for option, default in DEFAULT_CONFIG.items():
        if option not in current_options:
            if callable(default):
                default = default()
            if default != UNSET:
                missing_options.update({option: default})

    if missing_options:
        logger.info(f"Setting config: {missing_options}")
        snap.config.set(missing_options)


def is_connected(name: str) -> bool:
    """Check if a plug or slot is connected.

    :param name: the plug/slot name.
    :return: whether the plug/slot is connected.
    """
    try:
        subprocess.check_call(["snapctl", "is-connected", name])
        return True
    except subprocess.CalledProcessError:
        return False
