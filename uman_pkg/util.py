# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Utility functions for uman

This module provides common utility functions used across uman modules.
"""

import os

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout


def get_uboot_dir():
    """Get the U-Boot source directory

    Checks if current directory is a U-Boot tree, otherwise uses $USRC.

    Returns:
        str: Path to U-Boot source directory, or None if not found
    """
    # Check if current directory is a U-Boot tree
    if os.path.exists('./test/py/test.py'):
        return os.getcwd()

    # Try USRC environment variable
    usrc = os.environ.get('USRC')
    if usrc and os.path.exists(os.path.join(usrc, 'test/py/test.py')):
        return usrc

    return None


def setup_uboot_dir():
    """Find and change to the U-Boot source directory

    Returns:
        str: Path to U-Boot source directory, or None if not found
    """
    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return None

    if uboot_dir != os.getcwd():
        tout.info(f'Changing to U-Boot directory: {uboot_dir}')
        os.chdir(uboot_dir)

    return uboot_dir


def exec_cmd(cmd, dry_run=False, env=None, capture=True):
    """Run a command or show what would be run in dry-run mode

    Args:
        cmd (list): Command to run
        dry_run (bool): If True, just show command without running
        env (dict): Optional environment variables to set
        capture (bool): Whether to capture output (default True)

    Returns:
        CommandResult or None: Result if run, None if dry-run
    """
    if dry_run:
        tout.notice(' '.join(cmd))
        if env:
            for key, value in env.items():
                tout.notice(f"  {key}={value}")
        return None

    tout.info(f"Running: {' '.join(cmd)}")
    return command.run_pipe([cmd], env=env, capture=capture,
                            raise_on_error=False)
