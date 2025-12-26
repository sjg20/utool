# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Settings handling for utool

This module provides access to the utool configuration file (~/.utool).
"""

import configparser
import os

# pylint: disable=import-error
from u_boot_pylib import tout

# Default config file content
DEFAULT_CONFIG = '''# utool config file

[DEFAULT]
# Build directory for U-Boot out-of-tree builds
build_dir = /tmp/b

# U-Boot test hooks directory
test_hooks = /vid/software/devel/ubtest/u-boot-test-hooks
'''

# Global settings storage
SETTINGS = {'config': None}


def get_all():
    """Get or create the global settings instance

    Returns:
        configparser.ConfigParser: Settings object
    """
    if SETTINGS['config'] is None:
        SETTINGS['config'] = configparser.ConfigParser()
        fname = os.path.expanduser('~/.utool')
        if not os.path.exists(fname):
            tout.notice(f'Creating config file: {fname}')
            with open(fname, 'w', encoding='utf-8') as fil:
                fil.write(DEFAULT_CONFIG)
        SETTINGS['config'].read(fname)
    return SETTINGS['config']


def get(name, fallback=None):
    """Get a setting by name

    Args:
        name (str): Name of setting to retrieve
        fallback (str or None): Value to return if the setting is missing

    Returns:
        str or None: Setting value with ~ and env vars expanded, or fallback
    """
    cfg = get_all()
    raw = cfg.get('DEFAULT', name, fallback=fallback)
    if raw is None:
        return None
    return os.path.expandvars(os.path.expanduser(raw))
