# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Test command for running U-Boot sandbox tests

This module handles the 'test' subcommand which runs U-Boot's unit tests
in sandbox.
"""

import os
import re

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from utool_pkg import settings


def get_sandbox_path():
    """Get path to the sandbox U-Boot executable

    Returns:
        str: Path to sandbox u-boot, or None if not found
    """
    build_dir = settings.get('build_dir', '/tmp/b')
    sandbox_path = os.path.join(build_dir, 'sandbox', 'u-boot')
    if os.path.exists(sandbox_path):
        return sandbox_path
    return None


def get_suites_from_nm(sandbox):
    """Get available test suites by parsing nm output

    Looks for symbols matching 'suite_end_<name>' pattern.

    Args:
        sandbox (str): Path to sandbox executable

    Returns:
        list: Sorted list of suite names
    """
    result = command.run_one('nm', sandbox, capture=True)
    suites = re.findall(r'\bsuite_end_(\w+)', result.stdout)
    return sorted(set(suites))


def get_tests_from_nm(sandbox, suite=None):
    """Get available tests by parsing nm output

    Looks for symbols matching '_u_boot_list_2_ut_<suite>_2_<test>' pattern.

    Args:
        sandbox (str): Path to sandbox executable
        suite (str): Optional suite name to filter tests

    Returns:
        list: Sorted list of (suite, test) tuples
    """
    result = command.run_one('nm', sandbox, capture=True)
    if suite:
        pattern = rf'_u_boot_list_2_ut_{suite}_2_(\w+)'
        matches = re.findall(pattern, result.stdout)
        return sorted(set((suite, test) for test in matches))

    # Find all tests across all suites
    pattern = r'_u_boot_list_2_ut_(\w+?)_2_(\w+)'
    matches = re.findall(pattern, result.stdout)
    return sorted(set(matches))


def list_suites(args):
    """List available test suites with test counts

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    sandbox = get_sandbox_path()
    if not sandbox:
        tout.error('Sandbox not built - run: utool b sandbox')
        return 1

    if args.dry_run:
        tout.notice(f'nm {sandbox}')
        return 0

    suites = get_suites_from_nm(sandbox)
    tests = get_tests_from_nm(sandbox)

    # Count tests per suite
    counts = {}
    for suite, _ in tests:
        counts[suite] = counts.get(suite, 0) + 1

    # Find width needed for count column
    max_count = max(counts.values()) if counts else 0
    width = max(len(str(max_count)), 5)

    print(f'{"Tests":>{width}} Suite')
    for suite in suites:
        print(f'{counts.get(suite, 0):{width}} {suite}')
    return 0


def list_tests(args):
    """List available tests

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    sandbox = get_sandbox_path()
    if not sandbox:
        tout.error('Sandbox not built - run: utool b sandbox')
        return 1

    if args.dry_run:
        tout.notice(f'nm {sandbox}')
        return 0

    tests = get_tests_from_nm(sandbox)
    for suite, test in tests:
        print(f'{suite} {test}')
    return 0


def do_test(args):
    """Handle test command - run U-Boot sandbox tests

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    if args.list_suites:
        return list_suites(args)

    if args.list_tests:
        return list_tests(args)

    # Running tests will be implemented later
    tout.error('Running tests not yet implemented')
    return 1
