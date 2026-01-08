# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Config command for examining U-Boot configuration

This module handles the 'config' subcommand which provides tools for
examining U-Boot .config files.
"""

import os
import re

# pylint: disable=import-error
from u_boot_pylib import tout

from uman_pkg import settings


def get_config_path(board, build_dir=None):
    """Get the path to the .config file for a board

    Args:
        board (str): Board name
        build_dir (str): Build directory override, or None for default

    Returns:
        str: Path to the .config file
    """
    if not build_dir:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = os.path.join(base_dir, board)
    return os.path.join(build_dir, '.config')


def do_grep(args):
    """Grep the .config file for a pattern

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    board = args.board or os.environ.get('b')
    if not board:
        tout.error('Board is required: use -B BOARD or set $b')
        return 1

    config_path = get_config_path(board, args.build_dir)
    if not os.path.exists(config_path):
        tout.error(f'Config file not found: {config_path}')
        tout.error(f'Build the board first: um b {board}')
        return 1

    pattern = args.grep
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        tout.error(f'Invalid regex pattern: {exc}')
        return 1

    with open(config_path, 'r', encoding='utf-8') as inf:
        for line in inf:
            if regex.search(line):
                print(line.rstrip())

    return 0


def run(args):
    """Handle config command

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    if args.grep:
        return do_grep(args)

    tout.error('No action specified (use -g PATTERN)')
    return 1
