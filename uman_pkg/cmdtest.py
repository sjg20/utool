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

from uman_pkg import settings

# Patterns for parsing linker-list symbols from nm output
# Format: _u_boot_list_2_ut_<suite>_2_<test>
RE_TEST_ALL = re.compile(r'_u_boot_list_2_ut_(\w+?)_2_(\w+)')
RE_TEST_SUITE = r'_u_boot_list_2_ut_{}_2_(\w+)'


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

    U-Boot uses linker lists to register unit tests. Each test creates a
    symbol with the pattern '_u_boot_list_2_ut_<suite>_2_<test>', where
    '_2_' represents the linker-list section separator.

    Args:
        sandbox (str): Path to sandbox executable
        suite (str): Optional suite name to filter tests

    Returns:
        list: Sorted list of (suite, test) tuples, e.g. [('dm', 'test_acpi')]
    """
    result = command.run_one('nm', sandbox, capture=True)
    if suite:
        matches = re.findall(RE_TEST_SUITE.format(suite), result.stdout)
        return sorted(set((suite, test) for test in matches))

    # Find all tests across all suites
    matches = RE_TEST_ALL.findall(result.stdout)
    return sorted(set(matches))


def build_ut_cmd(sandbox, tests, flattree=False, verbose=False):
    """Build the sandbox command line for running tests

    Args:
        sandbox (str): Path to sandbox executable
        tests (list): List of test specifications (suite or suite.test)
        flattree (bool): Use flat device tree instead of live tree
        verbose (bool): Enable verbose test output

    Returns:
        list: Command and arguments
    """
    cmd = [sandbox]

    # Add flat device tree flag if requested
    if flattree:
        cmd.append('-D')

    # Build the ut command string
    if tests:
        # Parse test specs - can be 'suite' or 'suite.test'
        ut_args = []
        for spec in tests:
            if '.' in spec:
                suite, test = spec.split('.', 1)
                ut_args.append(f'{suite} {test}')
            else:
                ut_args.append(spec)
        ut_cmd = f"ut {' '.join(ut_args)}"
    else:
        # Run all tests
        ut_cmd = 'ut all'

    # Add verbose flag to ut command
    if verbose:
        ut_cmd += ' -v'

    cmd.extend(['-c', ut_cmd])
    return cmd


def run_tests(sandbox, tests, args):
    """Run sandbox tests

    Args:
        sandbox (str): Path to sandbox executable
        tests (list): List of test specifications
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code from tests
    """
    flattree = args.flattree
    verbose = args.test_verbose
    cmd = build_ut_cmd(sandbox, tests, flattree=flattree, verbose=verbose)
    tout.info(f"Running: {' '.join(cmd)}")

    result = command.run_one(*cmd, capture=False)
    return result.return_code


def do_test(args):
    """Handle test command - run U-Boot sandbox tests

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    sandbox = get_sandbox_path()
    if not sandbox:
        tout.error('Sandbox not found. Build it first with: uman build sandbox')
        return 1

    # Handle list suites
    if args.list_suites:
        suites = get_suites_from_nm(sandbox)
        tout.notice('Available test suites:')
        for suite in suites:
            print(f'  {suite}')
        return 0

    # Handle list tests
    if args.list_tests:
        suite = args.tests[0] if args.tests else None
        tests = get_tests_from_nm(sandbox, suite)
        if suite:
            tout.notice(f'Tests in suite "{suite}":')
        else:
            tout.notice('Available tests:')
        for suite_name, test_name in tests:
            print(f'  {suite_name}.{test_name}')
        return 0

    # Run tests
    return run_tests(sandbox, args.tests, args)
