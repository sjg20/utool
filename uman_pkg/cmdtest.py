# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Test command for running U-Boot sandbox tests

This module handles the 'test' subcommand which runs U-Boot's unit tests
in sandbox.
"""

from collections import namedtuple
import os
import re
import time

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from uman_pkg import settings

# Named tuple for test result counts
TestCounts = namedtuple('TestCounts', ['passed', 'failed', 'skipped'])

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


def build_ut_cmd(sandbox, tests, flattree=False, verbose=False, legacy=False):
    """Build the sandbox command line for running tests

    Args:
        sandbox (str): Path to sandbox executable
        tests (list): List of test specifications (suite or suite.test)
        flattree (bool): Use flat device tree instead of live tree
        verbose (bool): Enable verbose test output
        legacy (bool): Legacy mode (don't use -E flag for older U-Boot)

    Returns:
        list: Command and arguments
    """
    cmd = [sandbox]

    # Add flat device tree flag if requested
    if flattree:
        cmd.append('-D')

    # Use -E to emit Result: lines (not for legacy U-Boot)
    emit = '' if legacy else '-E '

    # Build the ut command string with flags before suite name
    flags = '-v ' if verbose else ''
    if tests:
        # Parse test specs - can be 'suite' or 'suite.test'
        ut_args = []
        for spec in tests:
            if '.' in spec:
                suite, test = spec.split('.', 1)
                ut_args.append(f'{suite} {test}')
            else:
                ut_args.append(spec)
        ut_cmd = f"ut {emit}{flags}{' '.join(ut_args)}"
    else:
        # Run all tests
        ut_cmd = f'ut {emit}{flags}all'

    cmd.extend(['-c', ut_cmd])
    return cmd


def show_result(status, name):
    """Print a test result if showing results

    Args:
        status (str): Result status (PASS, FAIL, SKIP)
        name (str): Test name
    """
    print(f'  {status}: {name}')


def parse_legacy_results(output, show_results=False):
    """Parse legacy test output to extract results

    Handles old-style "Test: test_name ... ok/FAILED/SKIPPED" lines

    Args:
        output (str): Test output from sandbox
        show_results (bool): Print per-test results

    Returns:
        TestCounts or None: Counts of passed/failed/skipped, or None if none
    """
    passed = 0
    failed = 0
    skipped = 0

    for line in output.splitlines():
        name_match = re.search(r'Test:\s*(\S+)', line)
        name = name_match.group(1) if name_match else None
        lower = line.lower()

        if '... ok' in lower:
            status = 'PASS'
            passed += 1
        elif '... failed' in lower:
            status = 'FAIL'
            failed += 1
        elif '... skipped' in lower:
            status = 'SKIP'
            skipped += 1
        else:
            continue
        if show_results and name:
            show_result(status, name)

    if not passed and not failed and not skipped:
        return None
    return TestCounts(passed, failed, skipped)


def parse_results(output, show_results=False):
    """Parse test output to extract results from Result: lines

    Args:
        output (str): Test output from sandbox
        show_results (bool): Print per-test results

    Returns:
        TestCounts or None: Counts of passed/failed/skipped, or None if none
    """
    passed = 0
    failed = 0
    skipped = 0

    for line in output.splitlines():
        result_match = re.match(r'Result:\s*(PASS|FAIL|SKIP):?\s+(\S+)', line)
        if result_match:
            status, name = result_match.groups()
            if status == 'PASS':
                passed += 1
            elif status == 'FAIL':
                failed += 1
            elif status == 'SKIP':
                skipped += 1
            if show_results:
                show_result(status, name)

    if not passed and not failed and not skipped:
        return None
    return TestCounts(passed, failed, skipped)


def format_duration(seconds):
    """Format a duration in seconds as a human-readable string

    Args:
        seconds (float): Duration in seconds

    Returns:
        str: Formatted duration (e.g., "1.23s", "1m 23s")
    """
    if seconds < 60:
        return f'{seconds:.2f}s'
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f'{minutes}m {secs:.1f}s'


def run_tests(sandbox, tests, args):
    """Run sandbox tests

    Args:
        sandbox (str): Path to sandbox executable
        tests (list): List of test specifications
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code from tests
    """
    cmd = build_ut_cmd(sandbox, tests, flattree=args.flattree,
                       verbose=args.test_verbose, legacy=args.legacy)
    tout.info(f"Running: {' '.join(cmd)}")

    start_time = time.time()
    result = command.run_one(*cmd, capture=True)
    elapsed = time.time() - start_time

    # Print output to console only in verbose mode
    if result.stdout and verbose and not args.results:
        print(result.stdout, end='')

    # Parse and show results summary
    res = parse_results(result.stdout, show_results=args.results)
    if not res and args.legacy:
        res = parse_legacy_results(result.stdout, show_results=args.results)
    if res:
        tout.notice(f'Results: {res.passed} passed, {res.failed} failed, '
                    f'{res.skipped} skipped in {format_duration(elapsed)}')
        return result.return_code

    tout.warning('No results detected (use -L for older U-Boot)')
    return 1


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
