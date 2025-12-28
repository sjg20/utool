# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Test command for running U-Boot sandbox tests

This module handles the 'test' subcommand which runs U-Boot's unit tests
in sandbox.
"""

import fnmatch
import os
import re
import struct
import subprocess
import sys

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import cros_subprocess
from u_boot_pylib import tout

from utool_pkg import settings
from utool_pkg.util import get_uboot_dir, run_pytest


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


def get_section_info(sandbox):
    """Get .data.rel.ro section address and file offset

    Args:
        sandbox (str): Path to sandbox executable

    Returns:
        tuple: (section_addr, section_offset) or (None, None) if not found
    """
    result = command.run_one('readelf', '-S', sandbox, capture=True)
    match = re.search(r'\.data\.rel\.ro\s+PROGBITS\s+([0-9a-f]+)\s+([0-9a-f]+)',
                      result.stdout)
    if match:
        return int(match.group(1), 16), int(match.group(2), 16)
    return None, None


def get_test_flags(sandbox, suite):
    """Get flags for all tests in a suite by parsing the binary

    Reads the unit_test structs from the linker list to extract flags.

    struct unit_test {
        const char *file;     // offset 0
        const char *name;     // offset 8
        int (*func)();        // offset 16
        int flags;            // offset 24
        ...
    };

    Args:
        sandbox (str): Path to sandbox executable
        suite (str): Suite name to get flags for

    Returns:
        list: List of (test_name, flags) tuples
    """
    # Get symbol addresses
    result = command.run_one('nm', sandbox, capture=True)
    pattern = rf'([0-9a-f]+) D _u_boot_list_2_ut_{suite}_2_(\w+)'
    tests = re.findall(pattern, result.stdout)

    if not tests:
        return []

    section_addr, section_offset = get_section_info(sandbox)
    if section_addr is None:
        return []

    test_flags = []
    with open(sandbox, 'rb') as fh:
        for addr_str, name in tests:
            addr = int(addr_str, 16)
            file_offset = section_offset + (addr - section_addr)
            fh.seek(file_offset)
            data = fh.read(28)
            if len(data) < 28:
                continue
            _, _, _, flags = struct.unpack('<QQQI', data)
            test_flags.append((name, flags))

    return test_flags


# Unit test flags from include/test/test.h
UTF_FLAT_TREE = 0x08
UTF_LIVE_TREE = 0x10
UTF_DM = 0x80


def predict_test_count(sandbox, suite, flattree=False, pattern=None):
    """Predict how many times tests will run

    Args:
        sandbox (str): Path to sandbox executable
        suite (str): Suite name
        flattree (bool): Whether flattree tests are enabled (-f flag)
        pattern (str): Optional glob pattern to filter tests (e.g. 'video*')

    Returns:
        int: Predicted number of test runs
    """
    pre = f'{suite}_test_'
    plen = len(pre)

    def match(name):
        """Check if test name matches pattern (strip suite prefix first)"""
        short = name[plen:] if name.startswith(pre) else name
        return fnmatch.fnmatch(short, pattern)

    test_flags = get_test_flags(sandbox, suite)
    if not test_flags:
        return 0

    # Filter by pattern if provided
    if pattern:
        test_flags = [(n, f) for n, f in test_flags if match(n)]

    count = 0
    for name, flags in test_flags:
        # Tests with UTF_FLAT_TREE only run on flat tree
        if flags & UTF_FLAT_TREE:
            if flattree:
                count += 1
            continue

        # All other tests run once on live tree
        count += 1

        # Tests with UTF_DM run again on flat tree, except video tests
        if flattree and flags & UTF_DM and not flags & UTF_LIVE_TREE:
            # Video tests skip flattree (except video_base)
            if 'video' not in name or 'video_base' in name:
                count += 1

    return count


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


class TestProgress:
    """Track and display test progress"""

    def __init__(self, predicted_total=0):
        self.total = predicted_total
        self.run = 0
        self.suite = ''
        self.failures = 0
        self.output_lines = []
        self.failed_tests = []
        self.cur_test = None  # (name, output_lines) tuple when test is active

    def handle_output(self, _stream, data):
        """Process output from sandbox, updating progress

        Args:
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
                # Only use U-Boot's count if we don't have a prediction
                if not self.total:
                    self.total = int(match.group(1))
                self.suite = match.group(2)
                continue

            # Parse "Test: name: file.c"
            match = re.match(r'Test: (\w+): (\S+)', line)
            if match:
                # Check if previous test failed
                self._check_test_failure()
                self.cur_test = (match.group(1), [])
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
            if self.cur_test and line.strip():
                self.cur_test[1].append(line)

        return False

    def _check_test_failure(self):
        """Check if current test failed and show it immediately"""
        if not self.cur_test or not self.cur_test[1]:
            self.cur_test = None
            return

        name, output = self.cur_test
        # Check for actual failure indicators in output
        fail_patterns = ('Expected', 'failed', 'ASSERT', 'Error', 'Failure')
        is_failure = any(any(pat in line for pat in fail_patterns)
                         for line in output)
        if is_failure:
            self.clear_progress()
            print(f'{self.suite} {name}')
            for line in output:
                print(f'  {line}')
            self.failed_tests.append((self.suite, name))
        self.cur_test = None

    def _show_progress(self):
        """Display current progress on a single line"""
        if self.total:
            width = len(str(self.total))
            status = f'{self.run:>{width}}/{self.total} {self.suite}'
        else:
            status = f'{self.run} {self.suite}'
        sys.stdout.write(f'\r{status}')
        sys.stdout.flush()

    def clear_progress(self):
        """Clear the progress line"""
        sys.stdout.write('\r\033[K')
        sys.stdout.flush()


# Tests that require test_ut_dm_init to create data files
HOST_TESTS = ['cmd_host', 'host', 'host_dup']


def needs_dm_init(args):
    """Check if tests require dm init data files

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        bool: True if dm init is needed
    """
    if not args.tests:
        return True  # Running all tests

    for test in args.tests:
        # Check if running dm suite or all tests
        if test in ('dm', 'all'):
            return True
        # Check for specific host tests
        for host_test in HOST_TESTS:
            if host_test in test:
                return True
    return False


def ensure_dm_init_files():
    """Ensure dm init data files exist, creating them if needed

    Returns:
        bool: True if files exist or were created successfully
    """
    build_dir = settings.get('build_dir', '/tmp/b')
    persistent_dir = os.path.join(build_dir, 'sandbox', 'persistent-data')
    test_file = os.path.join(persistent_dir, '2MB.ext2.img')

    if os.path.exists(test_file):
        return True

    tout.notice('Creating dm test data files...')
    return run_pytest('test_ut.py::test_ut_dm_init')


def parse_test_specs(tests):
    """Parse test arguments into list of (suite, pattern) tuples

    Handles formats:
        - None or ['all'] -> [('all', None)]
        - ['dm'] -> [('dm', None)]
        - ['dm', 'video*'] -> [('dm', 'video*')]
        - ['dm video*'] -> [('dm', 'video*')]
        - ['log', 'lib'] -> [('log', None), ('lib', None)]

    Args:
        tests (list): Test arguments from command line

    Returns:
        list: List of (suite, pattern) tuples
    """
    if not tests or tests == ['all']:
        return [('all', None)]

    # Single arg with space -> suite + pattern
    if len(tests) == 1:
        parts = tests[0].split(None, 1)
        suite = parts[0]
        pattern = parts[1] if len(parts) > 1 else None
        return [(suite, pattern)]

    # Two args: could be suite+pattern or two suites
    # If second arg contains glob chars, treat as pattern
    if len(tests) == 2 and any(c in tests[1] for c in '*?['):
        return [(tests[0], tests[1])]

    # Multiple suites
    return [(suite, None) for suite in tests]


def build_sandbox_args(sandbox, specs, flattree):
    """Build sandbox command line arguments

    Args:
        sandbox (str): Path to sandbox executable
        specs (list): List of (suite, pattern) tuples
        flattree (bool): Whether to run flattree tests

    Returns:
        list: Command and arguments to run
    """
    # Skip flat tree tests by default
    sandbox_args = [sandbox, '-T']
    if not flattree:
        sandbox_args.append('-F')

    # Build ut commands separated by semicolons
    cmds = []
    for suite, pattern in specs:
        if pattern:
            cmds.append(f'ut {suite} {pattern}')
        else:
            cmds.append(f'ut {suite}')
    sandbox_args.extend(['-c', '; '.join(cmds)])

    return sandbox_args


def calc_predicted_count(sandbox, specs, flattree):
    """Calculate predicted test count based on test specs

    Args:
        sandbox (str): Path to sandbox executable
        specs (list): List of (suite, pattern) tuples
        flattree (bool): Whether flattree tests are enabled

    Returns:
        int: Predicted number of test runs
    """
    if specs == [('all', None)]:
        return sum(predict_test_count(sandbox, suite, flattree)
                   for suite in get_suites_from_nm(sandbox))

    return sum(predict_test_count(sandbox, suite, flattree, pattern)
               for suite, pattern in specs)


def setup_test_env():
    """Set up environment variables for test execution

    Returns:
        dict: Environment dictionary with persistent data directory set
    """
    build_dir = settings.get('build_dir', '/tmp/b')
    persistent_dir = os.path.join(build_dir, 'sandbox', 'persistent-data')
    env = os.environ.copy()
    env['U_BOOT_PERSISTENT_DATA_DIR'] = persistent_dir
    return env


def show_error_output(prog):
    """Show last few lines of output when no tests ran

    Args:
        prog (TestProgress): Progress tracker with output
    """
    all_output = ''.join(prog.output_lines)
    for line in all_output.splitlines()[-5:]:
        if line.strip():
            print(line)


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

    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return 1

    specs = parse_test_specs(args.tests)
    sandbox_args = build_sandbox_args(sandbox, specs, args.flattree)

    if args.dry_run:
        tout.notice(' '.join(sandbox_args))
        return 0

    # Ensure dm init data files exist if needed
    if needs_dm_init(args) and not ensure_dm_init_files():
        return 1

    predicted = calc_predicted_count(sandbox, specs, args.flattree)
    if predicted:
        tout.notice(f'Running {predicted} tests')
    prog = TestProgress(predicted)
    env = setup_test_env()

    proc = cros_subprocess.Popen(sandbox_args,
                                 stdin=None,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=uboot_dir,
                                 env=env)
    proc.communicate_filter(prog.handle_output)

    prog.clear_progress()
    if prog.failed_tests:
        print(f'{len(prog.failed_tests)}/{prog.run} test(s) failed')
    elif not prog.run and proc.returncode:
        show_error_output(prog)

    return 1 if prog.failed_tests else proc.returncode


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
