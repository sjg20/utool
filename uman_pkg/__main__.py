#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""U-Boot Manager (uman) - automates U-Boot development tasks"""

import os
import sys

# Allow imports to work when run as module
our_path = os.path.dirname(os.path.realpath(__file__))
parent_path = os.path.dirname(our_path)
sys.path.append(parent_path)
sys.path.append(os.path.expanduser('~/u/tools'))

# pylint: disable=import-error,wrong-import-position
from u_boot_pylib import test_util
from uman_pkg import cmdline
from uman_pkg import control
from uman_pkg import ftest


def run_uman():
    """Run uman

    This is the main program. It collects arguments and runs the appropriate
    control module function.
    """
    args = cmdline.parse_args()

    if not args.debug:
        sys.tracebacklimit = 0

    # Run self-tests if requested
    if args.cmd == 'selftest':
        to_run = (args.testname if hasattr(args, 'testname') and
                  args.testname not in [None, 'selftest'] else None)
        result = test_util.run_test_suites(
            'uman', args.debug, args.verbose, args.no_capture,
            args.test_preserve_dirs, None, to_run, None,
            [ftest.TestUmanCmdline, ftest.TestUmanCIVars, ftest.TestUmanCI,
             ftest.TestUmanControl, ftest.TestGitLabParser,
             ftest.TestUmanMergeRequest, ftest.TestSettings,
             ftest.TestSetupSubcommand])
        sys.exit(0 if result.wasSuccessful() else 1)

    # Run the appropriate command
    exit_code = control.run_command(args)
    sys.exit(exit_code)


if __name__ == '__main__':
    sys.exit(run_uman())
