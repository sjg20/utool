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


def parse_one_test(arg):
    """Parse a single test argument into (suite, pattern) tuple

    Args:
        arg (str): Test argument (suite, suite_test_name, "suite pattern",
                   test_name, or partial_name for searching all suites)

    Returns:
        tuple: (suite, pattern) where pattern may be None, or suite may be
               None to search all suites
    """
    parts = arg.split(None, 1)
    suite = parts[0]
    pattern = parts[1] if len(parts) > 1 else None

    # Check for suite.test format
    if '.' in suite and pattern is None:
        suite, pattern = suite.split('.', 1)
    # Check for full test name: suite_test_name
    elif '_test_' in suite:
        suite, pattern = suite.split('_test_', 1)
    # Check for test name only: test_something -> search all suites
    elif suite.startswith('test_'):
        pattern = suite[5:]  # Strip 'test_' prefix
        suite = None
    # Check for partial test name containing underscore (e.g. ext4l_unlink)
    elif '_' in suite and pattern is None:
        pattern = suite
        suite = None

    return (suite, pattern)


def parse_test_specs(tests):
    """Parse test arguments into list of (suite, pattern) tuples

    Handles formats:
        - None or ['all'] -> [('all', None)]
        - ['dm'] -> [('dm', None)]
        - ['dm', 'video*'] -> [('dm', 'video*')]
        - ['dm video*'] -> [('dm', 'video*')]
        - ['log', 'lib'] -> [('log', None), ('lib', None)]
        - ['bloblist_test_blob'] -> [('bloblist', 'blob')]
        - ['dm.test_acpi'] -> [('dm', 'test_acpi')]

    Args:
        tests (list): Test arguments from command line

    Returns:
        list: List of (suite, pattern) tuples
    """
    if not tests or tests == ['all']:
        return [('all', None)]

    # Single arg
    if len(tests) == 1:
        return [parse_one_test(tests[0])]

    # Two args: could be suite+pattern or two suites/tests
    # If second arg contains glob chars, treat as pattern
    if len(tests) == 2 and any(c in tests[1] for c in '*?['):
        return [(tests[0], tests[1])]

    # Multiple suites or full test names
    return [parse_one_test(t) for t in tests]


def resolve_specs(sandbox, specs):
    """Resolve specs with suite=None by looking up from nm

    Args:
        sandbox (str): Path to sandbox executable
        specs (list): List of (suite, pattern) tuples

    Returns:
        tuple: (resolved_specs, unmatched_specs)
    """
    resolved = []
    unmatched = []
    all_tests = None  # Lazy load

    for suite, pattern in specs:
        if suite is not None:
            resolved.append((suite, pattern))
        else:
            # Need to find suite(s) for this pattern
            if all_tests is None:
                all_tests = get_tests_from_nm(sandbox)
            found = False
            for test_suite, test_name in all_tests:
                if test_name.endswith(pattern):
                    resolved.append((test_suite, pattern))
                    found = True
                    break  # Only add first match
            if not found:
                unmatched.append((None, pattern))

    return resolved, unmatched


def validate_specs(sandbox, specs):
    """Check that each spec matches at least one test

    Args:
        sandbox (str): Path to sandbox executable
        specs (list): List of (suite, pattern) tuples

    Returns:
        list: List of unmatched specs (empty if all match)
    """
    if specs == [('all', None)]:
        return []

    all_tests = get_tests_from_nm(sandbox)
    unmatched = []

    for suite, pattern in specs:
        found = False
        for test_suite, test_name in all_tests:
            if test_suite != suite:
                continue
            if pattern is None:
                found = True
                break
            if test_name.endswith(pattern):
                found = True
                break
        if not found:
            unmatched.append((suite, pattern))

    return unmatched


def build_ut_cmd(sandbox, specs, flattree=False, verbose=False, legacy=False):
    """Build the sandbox command line for running tests

    Args:
        sandbox (str): Path to sandbox executable
        specs (list): List of (suite, pattern) tuples from parse_test_specs
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

    # Build ut commands from specs; use -E to emit Result: lines (not for legacy)
    emit = '' if legacy else '-E '
    flags = '-v ' if verbose else ''
    cmds = []
    for suite, pattern in specs:
        if pattern:
            ut_cmd = f'ut {emit}{flags}{suite} {pattern}'
        else:
            ut_cmd = f'ut {emit}{flags}{suite}'
        cmds.append(ut_cmd)

    cmd.extend(['-c', '; '.join(cmds)])
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


def run_tests(sandbox, specs, args):
    """Run sandbox tests

    Args:
        sandbox (str): Path to sandbox executable
        specs (list): List of (suite, pattern) tuples from parse_test_specs
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code from tests
    """
    cmd = build_ut_cmd(sandbox, specs, flattree=args.flattree,
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


def do_test(args):  # pylint: disable=R0912
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

    # Parse test specs
    specs = parse_test_specs(args.tests)

    # Resolve any specs that need suite lookup
    specs, unmatched = resolve_specs(sandbox, specs)
    if unmatched:
        for suite, pattern in unmatched:
            tout.error(f'No tests found matching: {pattern}')
        return 1

    # Validate that specs match actual tests
    unmatched = validate_specs(sandbox, specs)
    if unmatched:
        for suite, pattern in unmatched:
            if pattern:
                tout.error(f'No tests found matching: {suite}.{pattern}')
            else:
                tout.error(f'No tests found in suite: {suite}')
        return 1

    # Run tests
    return run_tests(sandbox, specs, args)
