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
from u_boot_pylib import command
from u_boot_pylib import tout

from uman_pkg import settings
from uman_pkg.util import exec_cmd, setup_uboot_dir


# ELF files to process (relative to build directory)
ELF_TARGETS = [
    'u-boot',
    'spl/u-boot-spl',
    'tpl/u-boot-tpl',
    'vpl/u-boot-vpl',
]


def get_execs(build_dir):
    """Iterate over ELF targets that exist in the build directory

    Args:
        build_dir (str): Path to build directory

    Yields:
        str: Full path to each existing ELF file
    """
    for target in ELF_TARGETS:
        elf_path = os.path.join(build_dir, target)
        if os.path.exists(elf_path):
            yield elf_path


def get_cross_tool(board, tool):
    """Get a cross-compiled tool for a board

    Args:
        board (str): Board name
        tool (str): Tool name (e.g. 'objdump', 'nm', 'size')

    Returns:
        str: Cross-compiled tool name (e.g. 'arm-linux-gnueabi-objdump')
    """
    prefix = command.output_one_line('buildman', '-A', '--boards', board)
    return f'{prefix}{tool}'


def run_objdump(build_dir, board, args):
    """Run objdump on built ELF files to create disassembly

    Args:
        build_dir (str): Path to build directory
        board (str): Board name (for cross toolchain)
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Number of files disassembled
    """
    objdump = get_cross_tool(board, 'objdump')

    count = 0
    for elf_path in get_execs(build_dir):
        dis_path = f'{elf_path}.dis'
        tout.info(f'Disassembling {elf_path}')
        if not args.dry_run:
            result = command.run_one(objdump, '-d', '-S', elf_path)
            with open(dis_path, 'w', encoding='utf-8') as outf:
                outf.write(result.stdout)
        count += 1
    return count


def show_size(build_dir, args):
    """Show size information for built ELF files

    Args:
        build_dir (str): Path to build directory
        args (argparse.Namespace): Arguments from cmdline
    """
    elf_files = list(get_execs(build_dir))
    if not elf_files:
        tout.warning('No ELF files found')
        return

    result = exec_cmd(['size'] + elf_files, args.dry_run)
    if result:
        print(result.stdout)


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
    if args.in_tree:
        cmd = ['buildman', '-i', '--boards', board]
    else:
        cmd = ['buildman', '-I', '-w', '--boards', board, '-o', build_dir]
    if not args.lto:
        cmd.insert(1, '-L')
    if args.target:
        cmd.extend(['--target', args.target])
    if args.jobs:
        cmd.extend(['-j', str(args.jobs)])
    if args.force_reconfig:
        cmd.append('-C')
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

    build_dir = args.output_dir or get_dir(board)

    if args.fresh and os.path.exists(build_dir):
        tout.info(f'Removing output directory: {build_dir}')
        if not args.dry_run:
            shutil.rmtree(build_dir)

    tout.info(f'Building U-Boot for board: {board}')
    tout.info(f'Output directory: {build_dir}')

    cmd = get_cmd(args, board, build_dir)

    env = None
    if args.trace:
        env = os.environ.copy()
        env['FTRACE'] = '1'

    result = exec_cmd(cmd, args.dry_run, env=env, capture=False)

    if result is None:  # dry-run
        if args.objdump:
            run_objdump(build_dir, board, args)
        if args.size:
            show_size(build_dir, args)
        return 0

    if result.return_code != 0:
        tout.info('Build failed')
        return result.return_code

    if args.objdump:
        count = run_objdump(build_dir, board, args)
        tout.notice(f'Disassembled {count} file(s)')

    if args.size:
        show_size(build_dir, args)

    tout.info('Build complete')
    return 0
