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

from u_boot_pylib import command

from utool_pkg import settings
from utool_pkg.util import exec_cmd, get_uboot_dir


# ELF files to disassemble (relative to build directory)
DISASM_TARGETS = [
    'u-boot',
    'spl/u-boot-spl',
    'tpl/u-boot-tpl',
    'vpl/u-boot-vpl',
]


def run_objdump(build_dir, args):
    """Run objdump on built ELF files to create disassembly

    Args:
        build_dir (str): Path to build directory
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Number of files disassembled
    """
    count = 0
    for target in DISASM_TARGETS:
        elf_path = os.path.join(build_dir, target)
        if os.path.exists(elf_path):
            dis_path = f'{elf_path}.dis'
            tout.info(f'Disassembling {target}')
            if not args.dry_run:
                result = command.run_pipe(
                    [['objdump', '-d', '-S', elf_path]],
                    capture=True, raise_on_error=False)
                if result.return_code == 0:
                    with open(dis_path, 'w', encoding='utf-8') as f:
                        f.write(result.stdout)
                    count += 1
                else:
                    tout.warning(f'Failed to disassemble {target}')
            else:
                count += 1
    return count


def show_size(build_dir, args):
    """Show size information for built ELF files

    Args:
        build_dir (str): Path to build directory
        args (argparse.Namespace): Arguments from cmdline
    """
    elf_files = []
    for target in DISASM_TARGETS:
        elf_path = os.path.join(build_dir, target)
        if os.path.exists(elf_path):
            elf_files.append(elf_path)

    if not elf_files:
        tout.warning('No ELF files found')
        return

    if args.dry_run:
        tout.notice(f"size {' '.join(elf_files)}")
        return

    result = command.run_pipe(
        [['size'] + elf_files],
        capture=True, raise_on_error=False)
    if result.return_code == 0:
        print(result.stdout)
    else:
        tout.warning('Failed to get size information')


def get_build_dir(board):
    """Get the build directory for a board

    Args:
        board (str): Board name

    Returns:
        str: Path to the build directory
    """
    base_dir = settings.get('build_dir', '/tmp/b')
    return os.path.join(base_dir, board)


def do_build(args):
    """Handle build command - build U-Boot for a board

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    if not args.board:
        tout.error('Board is required: use -b BOARD')
        return 1

    # Find U-Boot source directory
    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return 1

    # Change to U-Boot directory if needed
    if uboot_dir != os.getcwd():
        tout.info(f'Changing to U-Boot directory: {uboot_dir}')
        os.chdir(uboot_dir)

    base_dir = settings.get('build_dir', '/tmp/b')
    build_dir = os.path.join(base_dir, args.board)

    if args.fresh and os.path.exists(build_dir):
        tout.info(f'Removing output directory: {build_dir}')
        if not args.dry_run:
            shutil.rmtree(build_dir)

    tout.info(f'Building U-Boot for board: {args.board}')
    tout.info(f'Output directory: {build_dir}')

    if args.in_tree:
        cmd = ['buildman', '-i', '--boards', args.board]
    else:
        cmd = ['buildman', '-I', '-w', '--boards', args.board, '-o', build_dir]
    if args.lto:
        cmd.append('--lto')
    else:
        cmd.insert(1, '-L')
    if args.target:
        cmd.extend(['--target', args.target])
    if args.jobs:
        cmd.extend(['-j', str(args.jobs)])
    if args.force_reconfig:
        cmd.append('-C')

    env = None
    if args.trace:
        env = os.environ.copy()
        env['FTRACE'] = '1'

    result = exec_cmd(cmd, args, env=env, capture=False)

    if result is None:  # dry-run
        if args.objdump:
            run_objdump(build_dir, args)
        if args.size:
            show_size(build_dir, args)
        return 0

    if result.return_code != 0:
        tout.error('Build failed')
        return result.return_code

    if args.objdump:
        count = run_objdump(build_dir, args)
        tout.notice(f'Disassembled {count} file(s)')

    if args.size:
        show_size(build_dir, args)

    tout.info('Build complete')
    return 0
