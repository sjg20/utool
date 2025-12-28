# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Build command for building U-Boot

This module handles the 'build' subcommand which builds U-Boot for a
specified board using buildman.
"""

import os
import shutil

# pylint: disable=import-error
from u_boot_pylib import tout

from uman_pkg import settings
from uman_pkg.util import exec_cmd, setup_uboot_dir


def get_dir(board):
    """Get the build directory for a board

    Args:
        board (str): Board name

    Returns:
        str: Path to the build directory
    """
    base_dir = settings.get('build_dir', '/tmp/b')
    return os.path.join(base_dir, board)


def get_cmd(args, board, build_dir):
    """Build the buildman command line

    Args:
        args (argparse.Namespace): Arguments from cmdline
        board (str): Board name to build
        build_dir (str): Path to build directory

    Returns:
        list: Command and arguments for buildman
    """
    cmd = ['buildman', '-I', '-w', '--boards', board, '-o', build_dir]
    if not args.lto:
        cmd.insert(1, '-L')
    if args.target:
        cmd.extend(['--target', args.target])
    if args.jobs:
        cmd.extend(['-j', str(args.jobs)])
    return cmd


def run(args):
    """Handle build command - build U-Boot for a board

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    board = args.board or os.environ.get('b')
    if not board:
        tout.error('Board is required: use -b BOARD or set $b')
        return 1

    if not setup_uboot_dir():
        return 1

    build_dir = get_dir(board)

    if args.fresh and os.path.exists(build_dir):
        tout.info(f'Removing output directory: {build_dir}')
        if not args.dry_run:
            shutil.rmtree(build_dir)

    tout.info(f'Building U-Boot for board: {board}')
    tout.info(f'Output directory: {build_dir}')

    cmd = get_cmd(args, board, build_dir)

    result = exec_cmd(cmd, args, capture=False)

    if result is None:  # dry-run
        return 0

    if result.return_code != 0:
        tout.info('Build failed')
        return result.return_code

    tout.info('Build complete')
    return 0
