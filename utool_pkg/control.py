# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Handles the main control logic of utool

This module provides various functions called by the main program to implement
the features of utool.
"""

import sys

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from utool_pkg.gitlab_parser import GitLabCIParser  # pylint: disable=wrong-import-position


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
                       args.sjg or args.test_spec)

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


def exec_cmd(cmd, args):
    """Run a command or show what would be run in dry-run mode

    Args:
        cmd (list): Command to run
        args (argparse.Namespace): Arguments object containing dry_run flag

    Returns:
        CommandResult or None: Result if run, None if dry-run
    """
    if args.dry_run:
        # Only show git push commands in dry-run mode
        if cmd[0] == 'git' and cmd[1] == 'push':
            tout.notice(' '.join(cmd))
        return None

    tout.info(f"Running: {' '.join(cmd)}")
    return command.run_one(*cmd)


def git_push_branch(branch, args, ci_vars=None, upstream=False):
    """Push a branch to the 'ci' remote with optional CI variables

    Args:
        branch (str): Branch name to push
        args (argparse.Namespace): Command line arguments (contains force
            and dry_run flags)
        ci_vars (dict): Optional CI variables to include as push options
        upstream (bool): Whether to set upstream with -u flag

    Returns:
        CommandResult or None: Result of push command
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

    return exec_cmd(push_cmd, args)


def show_pytest_choices(parser):
    """Show all available pytest choices (boards + job names)

    Args:
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        int: Exit code (always 0)
    """
    tout.notice('Available pytest targets:')
    tout.notice('')
    tout.notice('Special values:')
    tout.notice('  1                    - Run all pytest jobs')
    tout.notice('')
    tout.notice('Board names (targets all jobs for that board):')
    for board in parser.boards:
        tout.notice(f'  {board}')

    tout.notice('')
    tout.notice('Job names (targets specific job variant):')
    for job in parser.job_names:
        tout.notice(f'  {job}')
    return 0


def show_sjg_choices(parser):
    """Show all available SJG_LAB choices

    Args:
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        int: Exit code (always 0)
    """
    tout.notice('Available SJG_LAB targets:')
    tout.notice('')
    tout.notice('Special values:')
    tout.notice('  1                    - Run all lab jobs')
    tout.notice('  (empty)              - Manual lab jobs only')
    tout.notice('')
    tout.notice('Lab names:')
    for role in parser.roles:
        tout.notice(f'  {role}')

    return 0


def validate_pytest_value(value, parser):
    """Validate a pytest value against available choices

    Args:
        value (str): Value to validate
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        bool: True if valid, False otherwise
    """
    if value in ('1', 'help'):
        return True
    return value in parser.boards or value in parser.job_names


def validate_sjg_value(value, parser):
    """Validate an SJG_LAB value against available choices

    Args:
        value (str): Value to validate
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        bool: True if valid, False otherwise
    """
    if value in ('1', '', 'help'):
        return True
    return value in parser.roles


def validate_ci_args(args):
    """Validate CI arguments and handle help requests

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code (0 for success, non-zero for failure, None to continue)
    """
    # Parse GitLab CI file once for validation and help requests
    parser = GitLabCIParser()

    # Handle help requests
    if args.pytest == 'help':
        return show_pytest_choices(parser)
    if args.sjg == 'help':
        return show_sjg_choices(parser)

    # Validate pytest argument
    if args.pytest is not None:
        if not validate_pytest_value(args.pytest, parser):
            tout.error(f'Invalid pytest value: {args.pytest}')
            tout.notice(f'To see available choices: {sys.argv[0]} ci -p help')
            return 1

    # Validate sjg argument
    if args.sjg is not None:
        if not validate_sjg_value(args.sjg, parser):
            tout.error(f'Invalid SJG_LAB value: {args.sjg}')
            tout.notice(f'To see available choices: {sys.argv[0]} ci -l help')
            return 1

    # All validation passed
    return None


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
        # Validate CI arguments and handle help requests
        result = validate_ci_args(args)
        if result is not None:
            return result

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
    branch = command.output_one_line('git', 'branch', '--show-current')

    if not branch:
        tout.error('Could not determine current branch')
        return 1

    tout.info(f'Current branch: {branch}')

    ci_vars = build_ci_vars(args)

    git_push_branch(branch, args, ci_vars=ci_vars)

    return 0
