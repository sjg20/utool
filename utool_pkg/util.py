# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Utility functions for utool

This module provides common utility functions used across utool modules.
"""

import os
import subprocess

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from utool_pkg import settings


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


def exec_cmd(cmd, args, env=None, capture=True):
    """Run a command or show what would be run in dry-run mode

    Args:
        cmd (list): Command to run
        args (argparse.Namespace): Arguments object containing dry_run flag
        env (dict): Optional environment variables to set
        capture (bool): Whether to capture output (default True)

    Returns:
        CommandResult or None: Result if run, None if dry-run
    """
    if args.dry_run:
        tout.notice(' '.join(cmd))
        if env:
            for key, value in env.items():
                tout.notice(f"  {key}={value}")
        return None

    tout.info(f"Running: {' '.join(cmd)}")
    return command.run_pipe([cmd], env=env, capture=capture,
                            raise_on_error=False)


def run_pytest(test_name, board='sandbox', build_dir=None, quiet=True):
    """Run a pytest test

    Args:
        test_name (str): Test to run (e.g. 'test_ut.py::test_ut_dm_init')
        board (str): Board name (default: 'sandbox')
        build_dir (str): Build directory, or None to use default
        quiet (bool): If True, capture output; if False, show output

    Returns:
        bool: True if test passed, False otherwise
    """
    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return False

    if not build_dir:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = os.path.join(base_dir, board)

    pytest_cmd = [
        'python3', '-m', 'pytest', '-q',
        f'test/py/tests/{test_name}',
        '-B', board,
        '--build-dir', build_dir,
    ]

    if quiet:
        result = subprocess.run(pytest_cmd, cwd=uboot_dir, capture_output=True,
                                check=False)
        if result.returncode:
            tout.error(f'pytest {test_name} failed')
            tout.error(result.stderr.decode('utf-8', errors='replace'))
            return False
    else:
        result = subprocess.run(pytest_cmd, cwd=uboot_dir, check=False)
        if result.returncode:
            return False

    return True
