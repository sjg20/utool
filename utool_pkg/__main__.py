#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Simon's development tool (utool) - automates development tasks"""

import os
import sys

# Allow imports to work when run as module
our_path = os.path.dirname(os.path.realpath(__file__))
parent_path = os.path.dirname(our_path)
sys.path.append(parent_path)
sys.path.append(os.path.expanduser('~/u/tools'))

# pylint: disable=import-error,wrong-import-position
from u_boot_pylib import test_util
from utool_pkg import cmdline
from utool_pkg import control
from utool_pkg import ftest


def run_utool():
    """Run utool

    This is the main program. It collects arguments and runs the appropriate
    control module function.
    """
    args = cmdline.parse_args()

    if not args.debug:
        sys.tracebacklimit = 0

    # Run tests if requested
    if args.cmd == 'test':
        to_run = (args.testname if hasattr(args, 'testname') and
                  args.testname not in [None, 'test'] else None)
        result = test_util.run_test_suites(
            'utool', args.debug, args.verbose,
            getattr(args, 'no_capture', False),
            getattr(args, 'test_preserve_dirs', False),
            None, to_run, None,
            [ftest.TestUtoolCmdline, ftest.TestUtoolCI, ftest.TestUtoolControl,
             ftest.TestGitLabParser, ftest.TestUtoolMergeRequest])
        sys.exit(0 if result.wasSuccessful() else 1)

    # Run the appropriate command
    exit_code = control.run_command(args)
    sys.exit(exit_code)


if __name__ == '__main__':
    sys.exit(run_utool())
