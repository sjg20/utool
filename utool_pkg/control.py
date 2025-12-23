# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Handles the main control logic of st tool

This module provides various functions called by the main program to implement
the features of st.
"""

import subprocess
import sys

# Import patman modules
sys.path.append('/home/sglass/u/tools')
from u_boot_pylib import tout  # pylint: disable=import-error,wrong-import-position


def build_ci_vars(args):
    """Build CI variables based on command line arguments

    Args:
        args (argparse.Namespace): Arguments object with CI flags

    Returns:
        dict: Dictionary of CI variables and their values
    """
    ci_vars = {
        'SUITES': '0',
        'PYTEST': '0',
        'WORLD': '0',
        'SJG_LAB': ''
    }

    if not args.null:
        ci_flags_set = (args.suites or args.pytest or args.world or
                       args.sjg)

        if not ci_flags_set:
            ci_vars['SUITES'] = '1'
            ci_vars['PYTEST'] = '1'
            ci_vars['WORLD'] = '1'
        else:
            if args.suites:
                ci_vars['SUITES'] = '1'
            # Use 'is not None' for args with nargs='?' to distinguish between
            # not provided (None) and provided with default value ('1')
            if args.pytest is not None:
                ci_vars['PYTEST'] = args.pytest
            if args.world:
                ci_vars['WORLD'] = '1'
            if args.sjg is not None:
                ci_vars['SJG_LAB'] = args.sjg
            if args.test_spec:
                ci_vars['TEST_SPEC'] = args.test_spec

    return ci_vars


def run_or_show_command(cmd, args):
    """Run a command or show what would be run in dry-run mode

    Args:
        cmd (list): Command to run
        args (argparse.Namespace): Arguments object containing dry_run flag

    Returns:
        subprocess.CompletedProcess or None: Result if run, None if dry-run
    """
    if args.dry_run:
        # Only show git push commands in dry-run mode
        if cmd[0] == 'git' and cmd[1] == 'push':
            tout.notice(' '.join(cmd))
        return None

    tout.info(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, check=True)


def git_push_branch(branch, args, ci_vars=None, upstream=False):
    """Push a branch to the 'ci' remote with optional CI variables

    Args:
        branch (str): Branch name to push
        args (argparse.Namespace): Command line arguments (contains force and dry_run flags)
        ci_vars (dict): Optional CI variables to include as push options
        upstream (bool): Whether to set upstream with -u flag

    Returns:
        subprocess.CompletedProcess or None: Result of push command
    """
    push_cmd = ['git', 'push']

    if args.force:
        push_cmd.append('--force')

    if upstream:
        push_cmd.append('-u')

    if ci_vars:
        for key, value in ci_vars.items():
            push_cmd.extend(['-o', f'ci.variable={key}={value}'])

    push_cmd.extend(['ci', branch])

    return run_or_show_command(push_cmd, args)


def run_command(args):
    """Run the appropriate command based on parsed arguments

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    # Set verbosity level
    tout.init(tout.INFO if args.verbose else tout.NOTICE)

    tout.info(f'Running command: {args.cmd}')

    if args.cmd == 'ci':
        return do_ci(args)

    tout.error(f'Unknown command: {args.cmd}')
    return 1


def do_ci(args):
    """Handle CI command - push current branch to trigger CI

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    result = subprocess.run(['git', 'branch', '--show-current'],
                          capture_output=True, text=True, check=True)
    branch = result.stdout.strip()

    if not branch:
        tout.error('Could not determine current branch')
        return 1

    tout.info(f'Current branch: {branch}')

    ci_vars = build_ci_vars(args)

    git_push_branch(branch, args, ci_vars=ci_vars)

    return 0
