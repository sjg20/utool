# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Handles parsing of utool arguments

Creates the argument parser and uses it to parse the arguments passed in
"""

import argparse
import sys


# Aliases for subcommands
ALIASES = {
    'test': ['t'],
    'pytest': ['py'],
}


class ErrorCatchingArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that catches errors instead of exiting"""
    def __init__(self, **kwargs):
        self.exit_state = None
        self.catch_error = False
        super().__init__(**kwargs)

    def error(self, message):
        if self.catch_error:
            # Store message for potential use
            pass
        super().error(message)

    def exit(self, status=0, message=None):
        if self.catch_error:
            self.exit_state = True
            return
        super().exit(status, message)


def add_ci_subparser(subparsers):
    """Add the 'ci' subparser"""
    ci = subparsers.add_parser('ci', help='Push current branch to CI')

    # Help text only - choices shown with 'help' argument

    ci.add_argument('--suites', '-s', action='store_true',
                    help='Enable SUITES')
    pytest_help = 'Enable PYTEST: to select a particular one: -p help'
    sjg_help = 'Enable SJG_LAB: to select a particular board: -l help'

    ci.add_argument('--pytest', '-p', nargs='?', const='1', default=None,
                    help=pytest_help)
    ci.add_argument('--world', '-w', action='store_true', help='Enable WORLD')
    ci.add_argument('--sjg', '-l', nargs='?', const='1', default=None,
                    help=sjg_help)
    ci.add_argument('--force', '-f', action='store_true',
                    help='Force push to remote branch')
    ci.add_argument('--null', '-0', action='store_true',
                    help='Set all CI vars to 0')
    ci.add_argument('--merge', '-m', action='store_true',
                    help='Create merge request')
    ci.add_argument('--test-spec', '-t', metavar='SPEC',
                    help="Override test spec (e.g. 'not sleep')")
    ci.add_argument('--dest', '-d', metavar='BRANCH', default=None,
                    help='Destination branch name (default: current branch)')
    return ci


def add_test_subparser(subparsers):
    """Add the 'test' subparser"""
    test = subparsers.add_parser(
        'test', aliases=ALIASES['test'],
        help='Run utool functional tests')
    test.add_argument(
        'testname', type=str, default=None, nargs='?',
        help='Specify the test to run')
    test.add_argument(
        '-N', '--no-capture', action='store_true',
        help='Disable capturing of console output in tests')
    test.add_argument(
        '-X', '--test-preserve-dirs', action='store_true',
        help='Preserve and display test-created directories')
    return test


def add_pytest_subparser(subparsers):
    """Add the 'pytest' subparser"""
    pyt = subparsers.add_parser(
        'pytest', aliases=ALIASES['pytest'],
        help='Run pytest tests for U-Boot')
    pyt.add_argument(
        'test_spec', type=str, nargs='*',
        help="Test specification (e.g. 'test_dm', 'not sleep')")
    pyt.add_argument(
        '-b', '--board', metavar='BOARD',
        help='Board name to test (required; use -l to list QEMU boards)')
    pyt.add_argument(
        '-l', '--list', action='store_true', dest='list_boards',
        help='List available QEMU boards')
    pyt.add_argument(
        '-T', '--timeout', type=int, metavar='SECS', default=300,
        help='Test timeout in seconds (default: 300)')
    pyt.add_argument(
        '--no-build', action='store_true',
        help='Skip building U-Boot (assume already built)')
    pyt.add_argument(
        '--build-dir', metavar='DIR',
        help='Override build directory (default: /tmp/b/BOARD)')
    pyt.add_argument(
        '-s', '--show-output', action='store_true',
        help='Show all test output in real-time (pytest -s)')
    pyt.add_argument(
        '-t', '--timing', type=float, nargs='?', const=0.1, default=None,
        metavar='SECS',
        help='Show test timing (default min: 0.1s)')
    pyt.add_argument(
        '-q', '--quiet', action='store_true',
        help='Quiet mode: only show build output, progress, and result')
    return pyt


def setup_parser():
    """Set up command-line parser

    Returns:
        argparse.Parser object
    """
    epilog = '''U-Boot development tool'''

    parser = ErrorCatchingArgumentParser(epilog=epilog)
    parser.add_argument(
        '-D', '--debug', action='store_true',
        help='Enable debugging (provides full traceback on error)')
    parser.add_argument(
        '-v', '--verbose', action='store_true', dest='verbose', default=False,
        help='Verbose output')
    parser.add_argument(
        '-n', '--dry-run', action='store_true',
        help='Show what would be executed without running commands')

    subparsers = parser.add_subparsers(dest='cmd', required=True)
    add_ci_subparser(subparsers)
    add_test_subparser(subparsers)
    add_pytest_subparser(subparsers)

    return parser


def parse_args(argv=None):
    """Parse command line arguments from sys.argv[]

    Args:
        argv (str or None): Arguments to process, or None to use sys.argv[1:]

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = setup_parser()

    if not argv:
        argv = sys.argv[1:]

    args = parser.parse_args(argv)

    # Resolve aliases
    for full, aliases in ALIASES.items():
        if args.cmd in aliases:
            args.cmd = full

    return args
