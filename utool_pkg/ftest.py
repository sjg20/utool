# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Functional tests for utool CI automation tool"""

# pylint: disable=import-error,wrong-import-position,ungrouped-imports

import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add the utool package to the path
utool_path = Path(__file__).parent
sys.path.insert(0, str(utool_path))

# Add u-boot tools to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../u/tools'))

from u_boot_pylib import terminal
from utool_pkg import cmdline, control


class TestBase(unittest.TestCase):
    """Base class for all utool tests"""
    preserve_indir = False
    preserve_outdirs = False
    toolpath = None
    verbosity = None
    no_capture = None

    @classmethod
    def setup_test_args(cls, preserve_indir=False, preserve_outdirs=False,
                        toolpath=None, verbosity=None, no_capture=None):
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Set up test arguments similar to other u-boot tools

        Args:
            preserve_indir (bool): Preserve input directories used by tests
            preserve_outdirs (bool): Preserve output directories used by tests
            toolpath (str): Path to tools directory
            verbosity (int): Verbosity level for output
            no_capture (bool): True to disable output capture during tests
        """
        cls.preserve_indir = preserve_indir
        cls.preserve_outdirs = preserve_outdirs
        cls.toolpath = toolpath
        cls.verbosity = verbosity
        cls.no_capture = no_capture
        if no_capture is not None:
            terminal.USE_CAPTURE = not no_capture


def make_args(**kwargs):
    """Create an argparse.Namespace with default CI arguments"""
    defaults = {
        'dry_run': False,
        'verbose': False,
        'debug': False,
        'suites': False,
        'pytest': None,
        'world': False,
        'sjg': None,
        'force': False,
        'null': False,
        'cmd': 'ci',
        'test_spec': None
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestUtoolCmdline(TestBase):
    """Test the command line parsing"""

    def test_ci_subcommand_parsing(self):
        """Test that CI subcommand is parsed correctly"""
        parser = cmdline.setup_parser()

        # Test basic CI command
        args = parser.parse_args(['ci'])
        self.assertEqual(args.cmd, 'ci')
        self.assertFalse(args.suites)
        self.assertIsNone(args.pytest)

        # Test CI with flags
        args = parser.parse_args(['ci', '--suites', '--pytest'])
        self.assertTrue(args.suites)
        self.assertEqual(args.pytest, '1')

        # Test short flags
        args = parser.parse_args(['ci', '-s', '-p', '-w'])
        self.assertTrue(args.suites)
        self.assertEqual(args.pytest, '1')
        self.assertTrue(args.world)

    def test_dry_run_flag(self):
        """Test that dry-run flag is parsed correctly"""
        parser = cmdline.setup_parser()

        # Test long flag
        args = parser.parse_args(['--dry-run', 'ci'])
        self.assertTrue(args.dry_run)

        # Test short flag
        args = parser.parse_args(['-n', 'ci'])
        self.assertTrue(args.dry_run)

        # Test without flag
        args = parser.parse_args(['ci'])
        self.assertFalse(args.dry_run)

    def test_no_command_required(self):
        """Test that a command is required"""
        parser = cmdline.setup_parser()

        # Test that no command raises SystemExit (argparse error)
        with terminal.capture():
            with self.assertRaises(SystemExit):
                parser.parse_args([])


class TestUtoolCIVars(TestBase):
    """Test CI variable building logic"""

    def test_build_ci_vars_no_ci(self):
        """Test build_ci_vars with --null flag"""
        args = make_args(null=True)
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': '0',
            'WORLD': '0',
            'SJG_LAB': ''
        }
        self.assertEqual(ci_vars, expected)

    def test_build_ci_vars_defaults(self):
        """Test build_ci_vars with no flags (defaults)"""
        args = make_args()
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '1',
            'PYTEST': '1',
            'WORLD': '1',
            'SJG_LAB': ''
        }
        self.assertEqual(ci_vars, expected)

    def test_build_ci_vars_specific_flags(self):
        """Test build_ci_vars with specific flags"""
        args = make_args(suites=True, sjg='1')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '1',
            'PYTEST': '0',
            'WORLD': '0',
            'SJG_LAB': '1'
        }
        self.assertEqual(ci_vars, expected)

    def test_build_ci_vars_sjg_lab_value(self):
        """Test build_ci_vars with sjg value"""
        args = make_args(sjg='rpi4')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': '0',
            'WORLD': '0',
            'SJG_LAB': 'rpi4'
        }
        self.assertEqual(ci_vars, expected)

    def test_build_ci_vars_test_spec(self):
        """Test build_ci_vars with --test-spec flag"""
        args = make_args(test_spec='not sleep')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': '0',
            'WORLD': '0',
            'SJG_LAB': '',
            'TEST_SPEC': 'not sleep'
        }
        self.assertEqual(ci_vars, expected)

    def test_build_ci_vars_all_flags(self):
        """Test build_ci_vars with all flags enabled"""
        args = make_args(suites=True, pytest='1', world=True, sjg='1')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '1',
            'PYTEST': '1',
            'WORLD': '1',
            'SJG_LAB': '1'
        }
        self.assertEqual(ci_vars, expected)


class TestUtoolCI(TestBase):
    """Test the CI command functionality"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = None
        self.original_cwd = os.getcwd()

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)

    def _create_git_repo(self):
        """Create a temporary git repository for testing"""
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)

        # Initialise git repo (capture output to keep it silent)
        subprocess.run(['git', 'init'], check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'],
                       check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'],
                       check=True, capture_output=True)

        # Create initial commit
        Path('test.txt').write_text('test content', encoding='utf-8')
        subprocess.run(['git', 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'],
                       check=True, capture_output=True)

    def test_ci_not_in_git_repo(self):
        """Test CI command fails when not in git repository"""
        # Change to a non-git directory
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            args = make_args()
            with terminal.capture():
                # Should raise CalledProcessError when git command fails
                with self.assertRaises(subprocess.CalledProcessError):
                    control.do_ci(args)

    def test_ci_default_variables(self):
        """Test CI command with default variables when no flags specified"""
        self._create_git_repo()

        args = make_args(dry_run=True)
        with terminal.capture():
            res = control.do_ci(args)
        self.assertEqual(res, 0)

    def test_ci_specific_variables(self):
        """Test CI command with specific variables"""
        self._create_git_repo()

        args = make_args(dry_run=True, suites=True, pytest='1', sjg='rpi4')
        with terminal.capture():
            res = control.do_ci(args)
        self.assertEqual(res, 0)


    def test_ci_no_ci_flag(self):
        """Test CI command with --null flag sets all vars to 0"""
        self._create_git_repo()

        args = make_args(dry_run=True, null=True)
        with terminal.capture():
            res = control.do_ci(args)
        self.assertEqual(res, 0)

    def test_run_or_show_command_dry_run(self):
        """Test run_or_show_command in dry-run mode"""
        args = make_args(dry_run=True, verbose=False)
        with terminal.capture():
            res = control.run_or_show_command(['echo', 'test'], args)
        self.assertIsNone(res)

    def test_run_or_show_command_normal(self):
        """Test run_or_show_command in normal mode"""
        args = make_args(dry_run=False, verbose=False)
        with terminal.capture():
            res = control.run_or_show_command(['echo', 'test'], args)
        self.assertIsNotNone(res)
        self.assertEqual(res.returncode, 0)


class TestUtoolControl(TestBase):
    """Test the control module functionality"""

    def test_run_command_ci(self):
        """Test run_command dispatches to CI correctly"""
        args = make_args(cmd='ci', dry_run=True)

        # Mock the CI function to avoid git operations
        original_do_ci = control.do_ci
        control.do_ci = lambda args: 0

        try:
            with terminal.capture():
                res = control.run_command(args)
            self.assertEqual(res, 0)
        finally:
            control.do_ci = original_do_ci

    def test_run_command_unknown(self):
        """Test run_command with unknown command"""
        args = make_args(cmd='unknown')
        with terminal.capture():
            res = control.run_command(args)
        self.assertEqual(res, 1)
