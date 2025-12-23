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
    ci.add_argument('--suites', '-s', action='store_true',
                    help='Enable SUITES')
    ci.add_argument('--pytest', '-p', nargs='?', const='1', default=None,
                    help='Enable PYTEST (optionally specify test spec)')
    ci.add_argument('--world', '-w', action='store_true', help='Enable WORLD')
    ci.add_argument('--sjg', '-l', nargs='?', const='1', default=None,
                    help='Set SJG_LAB (optionally specify board)')
    ci.add_argument('--force', '-f', action='store_true',
                    help='Force push to remote branch')
    ci.add_argument('--null', '-0', action='store_true',
                    help='Set all CI vars to 0')
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
