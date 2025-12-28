# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Test command for running U-Boot sandbox tests

This module handles the 'test' subcommand which runs U-Boot's unit tests
in sandbox.
"""

import os
import re
import subprocess
import sys

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import cros_subprocess
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


class TestProgress:  # pylint: disable=R0902
    """Track and display test progress"""

    def __init__(self):
        self.total = 0
        self.run = 0
        self.suite = ''
        self.failures = 0
        self.output_lines = []
        self.current_test = None
        self.current_test_output = []
        self.failed_tests = []

    def handle_output(self, stream, data):  # pylint: disable=W0613
        """Process output from sandbox, updating progress

        Args:
            stream (file): Output stream (stdout/stderr), unused
            data (bytes): Bytes received

        Returns:
            bool: True to terminate, False to continue
        """
        text = data.decode('utf-8', errors='replace')
        self.output_lines.append(text)

        for line in text.splitlines():
            # Parse "Running N suite tests"
            match = re.match(r'Running (\d+) (\w+) tests', line)
            if match:
                self.total = int(match.group(1))
                self.suite = match.group(2)
                continue

            # Parse "Test: name: file.c"
            match = re.match(r'Test: (\w+): (\S+)', line)
            if match:
                # Check if previous test failed
                self._check_test_failure()
                self.current_test = match.group(1)
                self.current_test_output = []
                self.run += 1
                self._show_progress()
                continue

            # Parse final result
            match = re.match(r'Tests run: (\d+),.*failures: (\d+)', line)
            if match:
                self._check_test_failure()
                self.failures = int(match.group(2))
                continue

            # Collect output for current test (skip boot messages before tests)
            if self.current_test and line.strip():
                self.current_test_output.append(line)

        return False

    def _check_test_failure(self):
        """Check if current test failed and show it immediately"""
        if self.current_test and self.current_test_output:
            # Test had output - likely a failure, show it now
            self.clear_progress()
            print(f'{self.suite} {self.current_test}')
            for line in self.current_test_output:
                print(f'  {line}')
            self.failed_tests.append((self.suite, self.current_test))

    def _show_progress(self):
        """Display current progress on a single line"""
        if self.total:
            status = f'{self.run}/{self.total} {self.suite}'
        else:
            status = f'{self.run} {self.suite}'
        sys.stdout.write(f'\r{status}')
        sys.stdout.flush()

    def clear_progress(self):
        """Clear the progress line"""
        sys.stdout.write('\r\033[K')
        sys.stdout.flush()


def run_tests(args):
    """Run U-Boot sandbox tests

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    sandbox = get_sandbox_path()
    if not sandbox:
        tout.error('Sandbox not built - run: utool b sandbox')
        return 1

    # Build the ut command arguments
    if args.tests:
        ut_args = ' '.join(args.tests)
    else:
        ut_args = 'all'

    cmd = f'ut {ut_args}'

    # Build sandbox command - skip flat tree tests by default
    sandbox_args = [sandbox, '-T']
    if not args.flattree:
        sandbox_args.append('-F')
    sandbox_args.extend(['-c', cmd])

    if args.dry_run:
        tout.notice(' '.join(sandbox_args))
        return 0

    progress = TestProgress()
    proc = cros_subprocess.Popen(sandbox_args,
                                 stdin=None,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
    proc.communicate_filter(progress.handle_output)

    progress.clear_progress()

    if proc.returncode or progress.failures or progress.failed_tests:
        if not progress.run:
            # No tests ran - show last few lines of output for error message
            all_output = ''.join(progress.output_lines)
            lines = all_output.splitlines()
            for line in lines[-5:]:
                if line.strip():
                    print(line)
        elif progress.failed_tests:
            print(f'{len(progress.failed_tests)} test(s) failed')
        return 1

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

    return run_tests(args)
