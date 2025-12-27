# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Functional tests for utool CI automation tool"""

# pylint: disable=import-error,too-many-lines

import argparse
import os
import shutil
import tempfile
import unittest
from unittest import mock

from u_boot_pylib import command
from u_boot_pylib import terminal
from u_boot_pylib import tools
from u_boot_pylib import tout
import gitlab

from utool_pkg import (build, cmdline, cmdpy, control, gitlab_parser, settings,
                       setup)

# Capture stdout and stderr for silent command execution
CAPTURE = {'capture': True, 'capture_stderr': True}


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
        # pylint: disable=too-many-arguments
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

    def tearDown(self):
        """Clean up and restore command.TEST_RESULT after each test"""
        command.TEST_RESULT = None


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
        'merge': False,
        'dest': None,
        'board': None,
        'test_spec': [],
        'timeout': 300,
        'no_build': False,
        'build_dir': None,
        'show_output': False,
        'timing': None,
        'list_boards': False,
        'quiet': False,
        'cmd': 'ci'
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
        self.assertEqual('ci', args.cmd)
        self.assertFalse(args.suites)
        self.assertIsNone(args.pytest)

        # Test CI with flags
        args = parser.parse_args(['ci', '--suites', '--pytest'])
        self.assertTrue(args.suites)
        self.assertEqual('1', args.pytest)

        # Test short flags
        args = parser.parse_args(['ci', '-s', '-p', '-w'])
        self.assertTrue(args.suites)
        self.assertEqual('1', args.pytest)
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
        with self.assertRaises(SystemExit):
            with terminal.capture():
                parser.parse_args([])

    def test_pytest_subcommand_parsing(self):
        """Test that pytest subcommand is parsed correctly"""
        parser = cmdline.setup_parser()

        # Test basic pytest command - board is required but not enforced by
        # argparse (checked in do_pytest)
        args = parser.parse_args(['pytest'])
        self.assertEqual(args.cmd, 'pytest')
        self.assertIsNone(args.board)
        self.assertEqual(args.test_spec, [])
        self.assertEqual(args.timeout, 300)

        # Test pytest with board specified
        args = parser.parse_args(['pytest', '-b', 'sandbox', 'test_dm'])
        self.assertEqual(args.test_spec, ['test_dm'])
        self.assertEqual(args.board, 'sandbox')

        # Test pytest with multi-word test spec (no quotes needed)
        args = parser.parse_args(['pytest', '-b', 'coreboot', 'not', 'sleep'])
        self.assertEqual(args.test_spec, ['not', 'sleep'])
        self.assertEqual(args.board, 'coreboot')

        # Test pytest with all flags
        args = parser.parse_args(['pytest', '-b', 'coreboot', 'test_dm',
                                 '-T', '600'])
        self.assertEqual(args.board, 'coreboot')
        self.assertEqual(args.test_spec, ['test_dm'])
        self.assertEqual(args.timeout, 600)

        # Test pytest alias (use cmdline.parse_args for alias resolution)
        args = cmdline.parse_args(['py', '-b', 'sandbox'])
        self.assertEqual(args.cmd, 'pytest')
        self.assertEqual(args.board, 'sandbox')


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
        self.assertEqual(expected, ci_vars)

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
        self.assertEqual(expected, ci_vars)

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
        self.assertEqual(expected, ci_vars)

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
        self.assertEqual(expected, ci_vars)

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
        self.assertEqual(expected, ci_vars)

    def test_build_ci_vars_specific_pytest_target(self):
        """Test build_ci_vars with specific pytest target (like coreboot)"""
        args = make_args(pytest='coreboot')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': 'coreboot',
            'WORLD': '0',
            'SJG_LAB': ''
        }
        self.assertEqual(expected, ci_vars)

    def test_build_ci_vars_pytest_with_sjg_lab(self):
        """Test build_ci_vars combining pytest target with sjg lab"""
        args = make_args(pytest='coreboot', sjg='bbb')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': 'coreboot',
            'WORLD': '0',
            'SJG_LAB': 'bbb'
        }
        self.assertEqual(expected, ci_vars)

    def test_build_ci_vars_pytest_and_test_spec_separate(self):
        """Test that -p and -t flags work independently"""
        # Board name with -p should only set PYTEST, not TEST_SPEC
        args = make_args(pytest='sandbox')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': 'sandbox',
            'WORLD': '0',
            'SJG_LAB': ''
        }
        self.assertEqual(expected, ci_vars)
        self.assertNotIn('TEST_SPEC', ci_vars)

        # Using both -p and -t flags together
        args = make_args(pytest='coreboot', test_spec='test_ofplatdata')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': 'coreboot',
            'WORLD': '0',
            'SJG_LAB': '',
            'TEST_SPEC': 'test_ofplatdata'
        }
        self.assertEqual(expected, ci_vars)

    def test_build_ci_vars_job_name_targeting(self):
        """Test build_ci_vars with job name targeting"""
        args = make_args(pytest='sandbox with clang test.py')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': 'sandbox with clang test.py',
            'WORLD': '0',
            'SJG_LAB': ''
        }
        self.assertEqual(expected, ci_vars)

        # Should not set TEST_SPEC for job names
        self.assertNotIn('TEST_SPEC', ci_vars)

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
        self.assertEqual(expected, ci_vars)

    def test_build_commit_tags_no_skip(self):
        """Test build_commit_tags with no skip flags (all enabled)"""
        args = make_args(suites=True, pytest='1', world=True, sjg='1')
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        self.assertEqual('', tags)

    def test_build_commit_tags_skip_all(self):
        """Test build_commit_tags with --null flag (skip all)"""
        args = make_args(null=True)
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        self.assertEqual(
            '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]', tags)

    def test_build_commit_tags_skip_specific(self):
        """Test build_commit_tags with specific stages enabled"""
        args = make_args(suites=True)  # Only suites enabled, others skip
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        self.assertEqual('[skip-pytest] [skip-world] [skip-sjg]', tags)

    def test_build_commit_tags_skip_world_only(self):
        """Test build_commit_tags with world skipped"""
        # suites and pytest enabled, world skipped
        args = make_args(suites=True, pytest='1')
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        self.assertEqual('[skip-world] [skip-sjg]', tags)

    def test_commit_message_tag_integration(self):
        """Test that tags are correctly integrated into commit message"""
        tags = '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]'

        # Empty description with tags
        self.assertEqual(tags, control.build_desc('', tags))

        # Existing description with tags
        exp = ('This is a test commit\n\nSome details about the change\n\n'
               '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]')
        self.assertEqual(
            exp, control.build_desc(
                'This is a test commit\n\nSome details about the change', tags))

        # No tags returns original description unchanged
        self.assertEqual(
            'Test description', control.build_desc('Test description', ''))

        # Empty description with no tags
        self.assertEqual('', control.build_desc('', ''))

class TestUtoolCI(TestBase):
    """Test the CI command functionality"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = None
        self.orig_cwd = os.getcwd()
        tout.init(tout.NOTICE)

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.orig_cwd)
        command.TEST_RESULT = None

    def _create_git_repo(self):
        """Create a temporary git repository for testing"""
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)

        # Initialise git repo
        command.run('git', 'init', **CAPTURE)
        command.run('git', 'config', 'user.name', 'Test User', **CAPTURE)
        command.run('git', 'config', 'user.email', 'test@example.com',
                    **CAPTURE)

        # Create initial commit
        tools.write_file('test.txt', b'test content')
        command.run('git', 'add', '.', **CAPTURE)
        command.run('git', 'commit', '-m', 'Initial commit', **CAPTURE)

    def test_ci_not_in_git_repo(self):
        """Test CI command fails when not in git repository"""
        # Use command.py's TEST_RESULT to simulate git failure
        def raise_git_error(**_kwargs):
            result = command.CommandResult(b'', b'not a git repo', b'', 1)
            raise command.CommandExc('git failed', result)

        command.TEST_RESULT = raise_git_error
        args = make_args()
        with self.assertRaises(command.CommandExc):
            with terminal.capture():
                control.do_ci(args)

    def test_ci_dry_run(self):
        """Test CI command shows git push in dry-run mode"""
        self._create_git_repo()

        args = make_args(dry_run=True)
        with terminal.capture() as (out, _):
            res = control.do_ci(args)
        self.assertEqual(0, res)
        self.assertEqual(
            'git push -o ci.variable=SUITES=1 -o ci.variable=PYTEST=1 '
            '-o ci.variable=WORLD=1 -o ci.variable=SJG_LAB= ci master\n',
            out.getvalue())

    def test_ci_specific_variables(self):
        """Test CI command with specific variables"""
        self._create_git_repo()

        args = make_args(dry_run=True, suites=True, pytest='1', sjg='rpi4')
        with terminal.capture() as (out, _):
            res = control.do_ci(args)
        self.assertEqual(0, res)
        self.assertEqual(
            'git push -o ci.variable=SUITES=1 -o ci.variable=PYTEST=1 '
            '-o ci.variable=WORLD=0 -o ci.variable=SJG_LAB=rpi4 ci master\n',
            out.getvalue())

    def test_ci_no_ci_flag(self):
        """Test CI command with --null flag sets all vars to 0"""
        self._create_git_repo()

        args = make_args(dry_run=True, null=True)
        with terminal.capture() as (out, _):
            res = control.do_ci(args)
        self.assertEqual(0, res)
        self.assertEqual(
            'git push -o ci.variable=SUITES=0 -o ci.variable=PYTEST=0 '
            '-o ci.variable=WORLD=0 -o ci.variable=SJG_LAB= ci master\n',
            out.getvalue())

    def test_exec_cmd_dry_run(self):
        """Test exec_cmd in dry-run mode shows command"""
        args = make_args(dry_run=True, verbose=False)
        with terminal.capture() as (out, err):
            res = control.exec_cmd(['echo', 'test'], args)
        self.assertIsNone(res)
        self.assertEqual('echo test\n', out.getvalue())
        self.assertFalse(err.getvalue())

    def test_exec_cmd_normal(self):
        """Test exec_cmd in normal mode"""
        args = make_args(dry_run=False, verbose=False)
        with terminal.capture() as (out, err):
            res = control.exec_cmd(['true'], args)
        self.assertIsNotNone(res)
        self.assertEqual(0, res.return_code)
        self.assertFalse(out.getvalue())
        self.assertFalse(err.getvalue())

    def test_git_push_destination_parsing(self):
        """Test git_push_branch destination parsing"""
        cap = []

        def mock_git(pipe_list, **_kwargs):
            cap.append(pipe_list[0])
            return command.CommandResult(stdout='', return_code=0)

        command.TEST_RESULT = mock_git

        # Test default destination (None means use current branch name)
        args = make_args(dry_run=False, dest=None)
        with terminal.capture():
            control.git_push_branch('test-branch', args)
        self.assertEqual(['git', 'push', 'ci', 'test-branch'], list(cap[-1]))

        # Test custom destination branch
        args = make_args(dry_run=False, dest='my-feature')
        with terminal.capture():
            control.git_push_branch('test-branch', args)
        self.assertEqual(['git', 'push', 'ci', 'test-branch:my-feature'],
                         list(cap[-1]))

        # Test with CI variables
        args = make_args(dry_run=False, dest='feature-test')
        ci_vars = {'PYTEST': '1', 'SUITES': '0'}
        with terminal.capture():
            control.git_push_branch('test-branch', args, ci_vars=ci_vars)
        self.assertEqual(
            ['git', 'push', '-o', 'ci.variable=PYTEST=1', '-o',
             'ci.variable=SUITES=0', 'ci', 'test-branch:feature-test'],
            list(cap[-1]))

        # Test with force flag
        args = make_args(dry_run=False, dest='force-test', force=True)
        with terminal.capture():
            control.git_push_branch('test-branch', args)
        self.assertEqual(['git', 'push', '--force', 'ci',
                          'test-branch:force-test'], list(cap[-1]))

        # Test with upstream flag
        args = make_args(dry_run=False, dest='upstream-test')
        with terminal.capture():
            control.git_push_branch('test-branch', args, upstream=True)
        self.assertEqual(['git', 'push', '-u', 'ci',
                          'test-branch:upstream-test'], list(cap[-1]))


class TestUtoolControl(TestBase):  # pylint: disable=too-many-public-methods
    """Test the control module functionality"""

    def setUp(self):
        """Set up test environment with fake U-Boot tree"""
        self.test_dir = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir)
        os.makedirs('test/py')
        tools.write_file('test/py/test.py', b'# test')

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.test_dir)
        command.TEST_RESULT = None

    def test_run_command_ci(self):
        """Test run_command dispatches to CI correctly"""
        args = make_args(cmd='ci', dry_run=True)

        # Mock the CI function to avoid git operations
        orig_do_ci = control.do_ci
        control.do_ci = lambda args: 0

        try:
            with terminal.capture() as (out, err):
                res = control.run_command(args)
            self.assertEqual(0, res)
            self.assertFalse(out.getvalue())
            self.assertFalse(err.getvalue())
        finally:
            control.do_ci = orig_do_ci

    def test_run_command_unknown(self):
        """Test run_command with unknown command"""
        args = make_args(cmd='unknown')
        with terminal.capture() as (out, err):
            res = control.run_command(args)
        self.assertEqual(1, res)
        self.assertFalse(out.getvalue())
        self.assertEqual('Unknown command: unknown\n', err.getvalue())

    def test_invalid_pytest_value(self):
        """Test validation of invalid pytest values"""
        args = make_args(cmd='ci', pytest='invalid_board')
        with terminal.capture() as (out, err):
            res = control.run_command(args)
        self.assertEqual(1, res)
        self.assertIn('ci -p help', out.getvalue())
        self.assertEqual('Invalid pytest value: invalid_board\n',
                         err.getvalue())

    def test_invalid_sjg_value(self):
        """Test validation of invalid SJG_LAB values"""
        args = make_args(cmd='ci', sjg='invalid_lab')
        with terminal.capture() as (out, err):
            res = control.run_command(args)
        self.assertEqual(1, res)
        self.assertIn('ci -l help', out.getvalue())
        self.assertEqual('Invalid SJG_LAB value: invalid_lab\n', err.getvalue())

    def test_pytest_command(self):
        """Test pytest command execution"""
        cap = []

        def mock_test_py(pipe_list, **_kwargs):
            cap.append(pipe_list[0])
            return command.CommandResult(stdout='', return_code=0)

        command.TEST_RESULT = mock_test_py

        # Test basic pytest command
        args = make_args(cmd='pytest', board='sandbox')
        with terminal.capture():
            res = control.run_command(args)
        self.assertEqual(res, 0)

        # Verify command structure
        cmd = cap[-1]
        self.assertTrue(cmd[0].endswith('/test/py/test.py'))
        self.assertIn('-B', cmd)
        self.assertIn('sandbox', cmd)
        # Default timeout (300) shouldn't add -o flag
        self.assertNotIn('-o', cmd)

        # Test pytest with test specification and custom timeout
        args = make_args(cmd='pytest', board='malta', test_spec=['test_dm'],
                        timeout=600)
        with terminal.capture():
            res = control.run_command(args)
        self.assertEqual(res, 0)

        cmd = cap[-1]
        self.assertIn('malta', cmd)
        self.assertIn('-k', cmd)
        self.assertIn('test_dm', cmd)
        self.assertIn('-o', cmd)
        self.assertIn('faulthandler_timeout=600', cmd)

    def test_valid_pytest_value(self):
        """Test validation of valid pytest values"""
        args = make_args(cmd='ci', pytest='sandbox', dry_run=True)

        # Mock the CI function to avoid git operations
        orig_do_ci = control.do_ci
        control.do_ci = lambda args: 0

        try:
            with terminal.capture() as (out, err):
                res = control.run_command(args)
            self.assertEqual(0, res)
            self.assertFalse(out.getvalue())
            self.assertFalse(err.getvalue())
        finally:
            control.do_ci = orig_do_ci

    def test_valid_sjg_value(self):
        """Test validation of valid SJG_LAB values"""
        args = make_args(cmd='ci', sjg='rpi4', dry_run=True)

        # Mock the CI function to avoid git operations
        orig_do_ci = control.do_ci
        control.do_ci = lambda args: 0

        try:
            with terminal.capture() as (out, err):
                res = control.run_command(args)
            self.assertEqual(0, res)
            self.assertFalse(out.getvalue())
            self.assertFalse(err.getvalue())
        finally:
            control.do_ci = orig_do_ci

    def test_pytest_board_required(self):
        """Test that pytest requires a board"""
        args = make_args(cmd='pytest', board=None)
        with terminal.capture() as (_, err):
            res = control.run_command(args)
        self.assertEqual(1, res)
        self.assertIn('Board is required', err.getvalue())

    def test_pytest_board_from_env(self):
        """Test that pytest uses $b environment variable"""
        cap = []

        def mock_test_py(pipe_list, **_kwargs):
            cap.append(pipe_list[0])
            return command.CommandResult(stdout='', return_code=0)

        command.TEST_RESULT = mock_test_py
        orig_env = os.environ.get('b')

        try:
            os.environ['b'] = 'sandbox'
            args = make_args(cmd='pytest', board=None)
            with terminal.capture():
                res = control.run_command(args)
            self.assertEqual(0, res)
            self.assertIn('sandbox', cap[-1])
        finally:
            if orig_env is not None:
                os.environ['b'] = orig_env
            elif 'b' in os.environ:
                del os.environ['b']

    def test_pytest_quiet_mode(self):
        """Test that quiet mode adds correct flags"""
        cap = []

        def mock_test_py(pipe_list, **_kwargs):
            cap.append(pipe_list[0])
            return command.CommandResult(stdout='', return_code=0)

        command.TEST_RESULT = mock_test_py

        args = make_args(cmd='pytest', board='sandbox', quiet=True)
        with terminal.capture():
            res = control.run_command(args)
        self.assertEqual(0, res)

        cmd = cap[-1]
        self.assertIn('--no-header', cmd)
        self.assertIn('--quiet-hooks', cmd)

    def test_pytest_list_boards(self):
        """Test listing QEMU boards"""
        def mock_buildman(**_kwargs):
            return command.CommandResult(
                stdout='qemu : 2 boards\n   qemu-arm qemu-riscv64\n',
                return_code=0)

        command.TEST_RESULT = mock_buildman

        args = make_args(cmd='pytest', list_boards=True)
        with terminal.capture() as (out, _):
            res = control.run_command(args)
        self.assertEqual(0, res)
        self.assertIn('qemu-arm', out.getvalue())
        self.assertIn('qemu-riscv64', out.getvalue())

    def test_get_uboot_dir_current(self):
        """Test get_uboot_dir finds U-Boot in current directory"""
        # setUp already created fake U-Boot tree in self.test_dir
        result = cmdpy.get_uboot_dir()
        self.assertEqual(self.test_dir, result)

    def test_get_uboot_dir_usrc_env(self):
        """Test get_uboot_dir uses $USRC when not in U-Boot tree"""
        # Create a non-U-Boot directory
        non_uboot_dir = tempfile.mkdtemp()
        orig_usrc = os.environ.get('USRC')

        try:
            # Change to non-U-Boot directory
            os.chdir(non_uboot_dir)
            # Point USRC to the setUp-created U-Boot tree
            os.environ['USRC'] = self.test_dir

            result = cmdpy.get_uboot_dir()
            self.assertEqual(self.test_dir, result)
        finally:
            os.chdir(self.test_dir)  # Restore for tearDown
            if orig_usrc is not None:
                os.environ['USRC'] = orig_usrc
            elif 'USRC' in os.environ:
                del os.environ['USRC']
            shutil.rmtree(non_uboot_dir)

    def test_get_uboot_dir_not_found(self):
        """Test get_uboot_dir returns None when no U-Boot tree found"""
        non_uboot_dir = tempfile.mkdtemp()
        orig_usrc = os.environ.get('USRC')

        try:
            os.chdir(non_uboot_dir)
            if 'USRC' in os.environ:
                del os.environ['USRC']

            result = cmdpy.get_uboot_dir()
            self.assertIsNone(result)
        finally:
            os.chdir(self.test_dir)  # Restore for tearDown
            if orig_usrc is not None:
                os.environ['USRC'] = orig_usrc
            shutil.rmtree(non_uboot_dir)

    def test_pytest_not_in_uboot_tree(self):
        """Test pytest fails when not in U-Boot tree and no $USRC"""
        non_uboot_dir = tempfile.mkdtemp()
        orig_usrc = os.environ.get('USRC')

        try:
            os.chdir(non_uboot_dir)
            if 'USRC' in os.environ:
                del os.environ['USRC']

            args = make_args(cmd='pytest', board='sandbox')
            with terminal.capture() as (_, err):
                res = control.run_command(args)
            self.assertEqual(1, res)
            self.assertIn('Not in a U-Boot tree', err.getvalue())
        finally:
            os.chdir(self.test_dir)  # Restore for tearDown
            if orig_usrc is not None:
                os.environ['USRC'] = orig_usrc
            shutil.rmtree(non_uboot_dir)

    def test_parse_hook_config(self):
        """Test parsing hook config files"""
        config_content = b'''# Comment line
console_impl=qemu
qemu_machine="virt"
qemu_binary=qemu-system-riscv64
qemu_extra_args="-m 1G -nographic"
qemu_kernel_args="-bios ${OPENSBI} -kernel ${U_BOOT_BUILD_DIR}/u-boot.bin"
'''
        config_path = os.path.join(self.test_dir, 'conf.test')
        tools.write_file(config_path, config_content)

        config = cmdpy.parse_hook_config(config_path)

        self.assertEqual('qemu', config['console_impl'])
        self.assertEqual('virt', config['qemu_machine'])
        self.assertEqual('qemu-system-riscv64', config['qemu_binary'])
        self.assertEqual('-m 1G -nographic', config['qemu_extra_args'])
        self.assertIn('${OPENSBI}', config['qemu_kernel_args'])

    def test_parse_hook_config_nonexistent(self):
        """Test parsing non-existent config file returns empty dict"""
        config = cmdpy.parse_hook_config('/nonexistent/path')
        self.assertEqual({}, config)

    def test_expand_vars(self):
        """Test shell variable expansion"""
        env = {
            'OPENSBI': '/path/to/opensbi.bin',
            'BUILD_DIR': '/tmp/build',
        }

        # Test simple expansion
        result = cmdpy.expand_vars('${OPENSBI}', env)
        self.assertEqual('/path/to/opensbi.bin', result)

        # Test multiple variables
        result = cmdpy.expand_vars('-bios ${OPENSBI} -dir ${BUILD_DIR}',
                                         env)
        self.assertEqual('-bios /path/to/opensbi.bin -dir /tmp/build', result)

        # Test unknown variable remains unchanged
        result = cmdpy.expand_vars('${UNKNOWN}', env)
        self.assertEqual('${UNKNOWN}', result)

    @mock.patch('utool_pkg.cmdpy.settings')
    @mock.patch('utool_pkg.cmdpy.socket')
    def test_get_qemu_command(self, mock_socket, mock_settings):
        """Test building QEMU command from config"""
        # Set up mock hostname
        mock_socket.gethostname.return_value = 'testhost'

        # Create config directory structure
        hooks_dir = os.path.join(self.test_dir, 'hooks')
        bin_dir = os.path.join(hooks_dir, 'bin')
        host_dir = os.path.join(bin_dir, 'testhost')
        os.makedirs(host_dir)

        # Create config file
        config_content = b'''console_impl=qemu
qemu_machine=virt
qemu_binary=qemu-system-riscv64
qemu_extra_args="-m 1G"
qemu_kernel_args="-kernel ${U_BOOT_BUILD_DIR}/u-boot.bin"
'''
        config_path = os.path.join(host_dir, 'conf.testboard_na')
        tools.write_file(config_path, config_content)

        # Mock settings
        mock_settings.get.side_effect = lambda key, fallback=None: {
            'test_hooks': hooks_dir,
            'build_dir': '/tmp/b',
        }.get(key, fallback)

        args = make_args(cmd='pytest', board='testboard', build_dir=None)
        result = cmdpy.get_qemu_command('testboard', args)

        self.assertIn('qemu-system-riscv64', result)
        self.assertIn('-M virt', result)
        self.assertIn('-m 1G', result)
        self.assertIn('/tmp/b/testboard/u-boot.bin', result)

    @mock.patch('utool_pkg.cmdpy.settings')
    def test_get_qemu_command_no_hooks(self, mock_settings):
        """Test get_qemu_command fails when test_hooks not configured"""
        mock_settings.get.return_value = None

        args = make_args(cmd='pytest', board='testboard')
        with terminal.capture():
            result = cmdpy.get_qemu_command('testboard', args)

        self.assertIsNone(result)


class TestGitLabParser(TestBase):
    """Test GitLab CI file parsing functionality"""

    def test_gitlab_ci_parser_class(self):
        """Test GitLabCIParser class functionality"""
        # Test direct class usage
        parser = gitlab_parser.GitLabCIParser()

        # Should have properties with lists
        self.assertIsInstance(parser.roles, list)
        self.assertIsInstance(parser.boards, list)
        self.assertIsInstance(parser.job_names, list)

    def test_validate_sjg_value(self):
        """Test SJG value validation with class"""
        parser = gitlab_parser.GitLabCIParser()

        # Test special case - should always be valid
        self.assertTrue(control.validate_sjg_value('1', parser))

        # Test with real parser data
        if parser.roles:
            valid_role = parser.roles[0]
            self.assertIn(valid_role, parser.roles)

        # Invalid value should not be in roles
        self.assertNotIn('definitely_invalid_role_12345', parser.roles)

    def test_validate_pytest_value(self):
        """Test pytest value validation with class"""
        parser = gitlab_parser.GitLabCIParser()

        # Test special case - should always be valid
        self.assertTrue(control.validate_pytest_value('1', parser))

        # Test with real parser data
        if parser.boards:
            valid_board = parser.boards[0]
            self.assertIn(valid_board, parser.boards)

        # Invalid value should not be in boards
        self.assertNotIn('definitely_invalid_board_12345', parser.boards)

    def test_job_names_extraction(self):
        """Test that job names are correctly extracted"""
        parser = gitlab_parser.GitLabCIParser()

        # Should find pytest job names
        self.assertIsInstance(parser.job_names, list)

        # Should include some known job patterns if GitLab CI file exists
        job_names_str = ' '.join(parser.job_names)
        if 'test.py' in job_names_str:
            # Should have at least one job ending with test.py
            has_test_py = any(job.endswith('test.py')
                              for job in parser.job_names)
            self.assertTrue(has_test_py)

    def test_parser_consistency(self):
        """Test that parser instances return consistent data"""
        # Multiple parser instances should return the same data
        parser1 = gitlab_parser.GitLabCIParser()
        parser2 = gitlab_parser.GitLabCIParser()

        # Data should be identical
        self.assertEqual(parser1.roles, parser2.roles)
        self.assertEqual(parser1.boards, parser2.boards)
        self.assertEqual(parser1.job_names, parser2.job_names)


class TestUtoolMergeRequest(unittest.TestCase):
    """Tests for merge request functionality"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        # Initialize git repo
        command.run('git', 'init', **CAPTURE)
        command.run('git', 'config', 'user.email', 'test@test.com', **CAPTURE)
        command.run('git', 'config', 'user.name', 'Test User', **CAPTURE)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)
        super().tearDown()

    def test_merge_request_parsing(self):
        """Test parsing of command line for merge request"""
        parser = cmdline.setup_parser()

        # Test --merge flag
        args = parser.parse_args(['ci', '--merge'])
        self.assertTrue(args.merge)

        # Test -m flag
        args = parser.parse_args(['ci', '-m'])
        self.assertTrue(args.merge)

        # Test default (no merge)
        args = parser.parse_args(['ci'])
        self.assertFalse(args.merge)

    def test_destination_parsing(self):
        """Test parsing of destination argument"""
        parser = cmdline.setup_parser()

        # Test default destination (None means use current branch name)
        args = parser.parse_args(['ci'])
        self.assertEqual(args.dest, None)

        # Test custom branch name
        args = parser.parse_args(['ci', '--dest', 'my-feature'])
        self.assertEqual(args.dest, 'my-feature')

        # Test branch with hash-like name
        args = parser.parse_args(['ci', '-d', 'cherry-abc123'])
        self.assertEqual(args.dest, 'cherry-abc123')

        # Test short flag
        args = parser.parse_args(['ci', '-d', 'develop'])
        self.assertEqual(args.dest, 'develop')

    @mock.patch('utool_pkg.control.gitlab_api')
    @mock.patch('utool_pkg.control.gitlab')
    @mock.patch('utool_pkg.control.extract_mr_info')
    @mock.patch('utool_pkg.control.gitutil')
    def test_merge_request_gitlab_error(self, mock_gitutil, mock_extract,
                                        mock_gitlab, mock_api):
        """Test that GitLab errors cause failure"""
        # Set up mocks
        mock_gitutil.get_branch.return_value = 'test-branch'
        mock_extract.return_value = ('Test Title', 'Test Description', '')
        mock_api.get_remote_url.return_value = \
            'https://gitlab.com/user/repo.git'
        mock_api.parse_url.return_value = ('gitlab.com', 'user/repo')
        mock_api.get_token.return_value = 'fake-token'

        # Make GitLab raise an error - use real exception class
        mock_gitlab.GitlabError = gitlab.GitlabError
        mock_gitlab.Gitlab.return_value.projects.get.side_effect = \
            gitlab.GitlabError('Connection failed')

        args = make_args(merge=True)
        with terminal.capture():
            result = control.do_merge_request(args)

        self.assertEqual(result, 1)

    @mock.patch('utool_pkg.control.gitlab_api')
    @mock.patch('utool_pkg.control.gitlab')
    @mock.patch('utool_pkg.control.extract_mr_info')
    @mock.patch('utool_pkg.control.gitutil')
    @mock.patch('utool_pkg.control.git_push_branch')
    def test_merge_request_update_existing(self, _mock_push, mock_gitutil,
                                           mock_extract, mock_gitlab, mock_api):
        """Test updating an existing merge request"""
        # Set up mocks
        mock_gitutil.get_branch.return_value = 'test-branch'
        mock_extract.return_value = ('New Title', 'New Description', '')
        mock_api.get_remote_url.return_value = \
            'https://gitlab.com/user/repo.git'
        mock_api.parse_url.return_value = ('gitlab.com', 'user/repo')
        mock_api.get_token.return_value = 'fake-token'
        mock_gitlab.GitlabError = gitlab.GitlabError

        # Mock existing MR
        mock_mr = mock.MagicMock()
        mock_mr.web_url = 'https://gitlab.com/user/repo/-/merge_requests/1'
        mock_project = mock.MagicMock()
        mock_project.mergerequests.list.return_value = [mock_mr]
        mock_gitlab.Gitlab.return_value.projects.get.return_value = mock_project

        args = make_args(merge=True)
        with terminal.capture():
            result = control.do_merge_request(args)

        self.assertEqual(result, 0)
        self.assertEqual(mock_mr.title, 'New Title')
        self.assertEqual(mock_mr.description, 'New Description')
        mock_mr.save.assert_called_once()


class TestSettings(unittest.TestCase):
    """Tests for settings module"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, '.utool')
        # Reset global settings state
        settings.SETTINGS['config'] = None

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        settings.SETTINGS['config'] = None

    def test_get_all_creates_config(self):
        """Test that get_all creates config file if missing"""
        # Patch expanduser to use our test directory
        orig_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: p.replace('~', self.test_dir)

        try:
            with terminal.capture():
                cfg = settings.get_all()
            self.assertIsNotNone(cfg)
            self.assertTrue(os.path.exists(self.config_file))
        finally:
            os.path.expanduser = orig_expanduser

    def test_get_with_fallback(self):
        """Test get returns fallback for missing keys"""
        # Create a minimal config file
        tools.write_file(self.config_file,
                         b'[DEFAULT]\nbuild_dir = /tmp/test\n')

        orig_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: p.replace('~', self.test_dir)

        try:
            with terminal.capture():
                # Existing setting
                self.assertEqual('/tmp/test', settings.get('build_dir'))
                # Missing setting with fallback
                val = settings.get('missing', 'default')
                self.assertEqual('default', val)
        finally:
            os.path.expanduser = orig_expanduser

    def test_get_expands_paths(self):
        """Test that get expands ~ and env vars"""
        tools.write_file(self.config_file,
                         b'[DEFAULT]\ntest_path = ~/mydir\n')

        orig_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: p.replace('~', self.test_dir)

        try:
            with terminal.capture():
                result = settings.get('test_path')
            self.assertEqual(f'{self.test_dir}/mydir', result)
        finally:
            os.path.expanduser = orig_expanduser

    def test_get_none_fallback(self):
        """Test that get returns None when fallback is None"""
        tools.write_file(self.config_file,
                         b'[DEFAULT]\nbuild_dir = /tmp/test\n')

        orig_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: p.replace('~', self.test_dir)

        try:
            with terminal.capture():
                result = settings.get('missing_key', fallback=None)
            self.assertIsNone(result)
        finally:
            os.path.expanduser = orig_expanduser


class TestSetupSubcommand(TestBase):
    """Tests for the setup subcommand"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        tout.init(tout.NOTICE)

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.test_dir)
        command.TEST_RESULT = None

    def test_setup_subcommand_parsing(self):
        """Test that setup subcommand is parsed correctly"""
        parser = cmdline.setup_parser()

        # Test basic setup command
        args = parser.parse_args(['setup'])
        self.assertEqual('setup', args.cmd)
        self.assertIsNone(args.component)
        self.assertFalse(args.list_components)
        self.assertFalse(args.force)

        # Test setup with component
        args = parser.parse_args(['setup', 'opensbi'])
        self.assertEqual('opensbi', args.component)

        # Test setup with --list flag
        args = parser.parse_args(['setup', '-l'])
        self.assertTrue(args.list_components)

        # Test setup with --force flag
        args = parser.parse_args(['setup', 'tfa', '-f'])
        self.assertEqual('tfa', args.component)
        self.assertTrue(args.force)

    def test_setup_list_components(self):
        """Test listing available components"""
        args = argparse.Namespace(
            cmd='setup',
            component=None,
            list_components=True,
            force=False,
            dry_run=False,
            verbose=False,
            debug=False
        )
        with terminal.capture() as (out, _):
            res = setup.do_setup(args)
        self.assertEqual(0, res)
        output = out.getvalue()
        self.assertIn('qemu', output)
        self.assertIn('opensbi', output)
        self.assertIn('tfa', output)
        self.assertIn('xtensa', output)

    def test_setup_unknown_component(self):
        """Test setup with unknown component"""
        args = argparse.Namespace(
            cmd='setup',
            component='unknown_component',
            list_components=False,
            force=False,
            dry_run=False,
            verbose=False,
            debug=False
        )
        with terminal.capture() as (_, err):
            res = setup.do_setup(args)
        self.assertEqual(1, res)
        self.assertIn('Unknown component', err.getvalue())

    def test_setup_qemu_all_installed(self):
        """Test setup_qemu when all packages are installed"""
        args = argparse.Namespace(dry_run=False, force=False)
        with mock.patch('utool_pkg.setup.command.output'):
            with terminal.capture() as (out, _):
                res = setup.setup_qemu(args)
        self.assertEqual(0, res)
        self.assertIn('All QEMU packages are installed', out.getvalue())

    def test_setup_qemu_dry_run(self):
        """Test setup_qemu in dry-run mode with missing packages"""
        def mock_output(*cmd):
            """Mock command.output to simulate missing qemu-system-ppc"""
            if 'qemu-system-ppc' in cmd:
                result = command.CommandResult(return_code=1, stdout='',
                                                stderr='', exception=None)
                raise command.CommandExc('Package not found', result)

        args = argparse.Namespace(dry_run=True, force=False)
        with mock.patch('utool_pkg.setup.command.output', mock_output):
            with terminal.capture() as (out, _):
                res = setup.setup_qemu(args)
        self.assertEqual(0, res)
        self.assertIn('Would run:', out.getvalue())

    def test_setup_opensbi_dry_run(self):
        """Test setup_opensbi in dry-run mode"""
        args = argparse.Namespace(dry_run=True, force=False)
        with terminal.capture() as (out, _):
            res = setup.setup_opensbi(self.test_dir, args)
        self.assertEqual(0, res)
        self.assertIn('Would download OpenSBI', out.getvalue())

    def test_setup_opensbi_already_present(self):
        """Test setup_opensbi when files already exist"""
        # Create fake opensbi files
        opensbi_dir = os.path.join(self.test_dir, 'opensbi')
        os.makedirs(opensbi_dir)
        tools.write_file(os.path.join(opensbi_dir, 'fw_dynamic.bin'), b'fake')
        tools.write_file(os.path.join(opensbi_dir, 'fw_dynamic_rv32.bin'),
                         b'fake')

        args = argparse.Namespace(dry_run=False, force=False)
        with terminal.capture() as (out, _):
            res = setup.setup_opensbi(self.test_dir, args)
        self.assertEqual(0, res)
        self.assertIn('already present', out.getvalue())

    def test_setup_tfa_dry_run(self):
        """Test setup_tfa in dry-run mode"""
        args = argparse.Namespace(dry_run=True, force=False)
        with terminal.capture() as (out, _):
            res = setup.setup_tfa(self.test_dir, args)
        self.assertEqual(0, res)
        self.assertIn('Would build TF-A', out.getvalue())

    def test_setup_tfa_already_present(self):
        """Test setup_tfa when files already exist"""
        # Create fake TF-A files
        tfa_dir = os.path.join(self.test_dir, 'tfa')
        os.makedirs(tfa_dir)
        tools.write_file(os.path.join(tfa_dir, 'bl1.bin'), b'fake')
        tools.write_file(os.path.join(tfa_dir, 'fip.bin'), b'fake')

        args = argparse.Namespace(dry_run=False, force=False)
        with terminal.capture() as (out, _):
            res = setup.setup_tfa(self.test_dir, args)
        self.assertEqual(0, res)
        self.assertIn('already present', out.getvalue())

    def test_setup_xtensa_dry_run(self):
        """Test setup_xtensa in dry-run mode"""
        args = argparse.Namespace(dry_run=True, force=False)
        with terminal.capture() as (out, _):
            res = setup.setup_xtensa(self.test_dir, args)
        self.assertEqual(0, res)
        self.assertIn('Would download Xtensa', out.getvalue())

    def test_setup_xtensa_already_present(self):
        """Test setup_xtensa when toolchain already exists"""
        # Create fake xtensa toolchain
        toolchain_dir = os.path.join(
            self.test_dir, 'xtensa/2020.07/xtensa-dc233c-elf/bin')
        os.makedirs(toolchain_dir)
        tools.write_file(os.path.join(toolchain_dir, 'xtensa-dc233c-elf-gcc'),
                         b'fake')

        args = argparse.Namespace(dry_run=False, force=False)
        with terminal.capture() as (out, _):
            res = setup.setup_xtensa(self.test_dir, args)
        self.assertEqual(0, res)
        self.assertIn('already present', out.getvalue())

    def test_setup_components_dict(self):
        """Test that SETUP_COMPONENTS has expected entries"""
        self.assertIn('qemu', setup.SETUP_COMPONENTS)
        self.assertIn('opensbi', setup.SETUP_COMPONENTS)
        self.assertIn('tfa', setup.SETUP_COMPONENTS)
        self.assertIn('xtensa', setup.SETUP_COMPONENTS)

    def test_qemu_packages_dict(self):
        """Test that QEMU_PACKAGES has expected entries"""
        self.assertIn('qemu-system-arm', setup.QEMU_PACKAGES)
        self.assertIn('qemu-system-misc', setup.QEMU_PACKAGES)
        self.assertIn('qemu-system-ppc', setup.QEMU_PACKAGES)
        self.assertIn('qemu-system-x86', setup.QEMU_PACKAGES)


class TestBuildSubcommand(TestBase):
    """Test build subcommand functionality"""

    def test_build_subcommand_parsing(self):
        """Test that build subcommand parses correctly"""
        args = cmdline.parse_args(['build', 'sandbox'])
        self.assertEqual('build', args.cmd)
        self.assertEqual('sandbox', args.board)

    def test_build_alias(self):
        """Test that 'b' alias works for build"""
        args = cmdline.parse_args(['b', 'sandbox'])
        self.assertEqual('build', args.cmd)
        self.assertEqual('sandbox', args.board)

    def test_build_lto_flag(self):
        """Test -l/--lto flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-l'])
        self.assertTrue(args.lto)

        args = cmdline.parse_args(['build', 'sandbox', '--lto'])
        self.assertTrue(args.lto)

    def test_build_fresh_flag(self):
        """Test -F/--fresh flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-F'])
        self.assertTrue(args.fresh)

    def test_build_target_option(self):
        """Test -t/--target option"""
        args = cmdline.parse_args(['build', 'sandbox', '-t', 'u-boot.bin'])
        self.assertEqual('u-boot.bin', args.target)

    def test_build_jobs_option(self):
        """Test -j/--jobs option"""
        args = cmdline.parse_args(['build', 'sandbox', '-j', '8'])
        self.assertEqual(8, args.jobs)

    def test_build_size_flag(self):
        """Test -s/--size flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-s'])
        self.assertTrue(args.size)

    def test_build_objdump_flag(self):
        """Test -O/--objdump flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-O'])
        self.assertTrue(args.objdump)

    def test_build_force_reconfig_flag(self):
        """Test -f/--force-reconfig flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-f'])
        self.assertTrue(args.force_reconfig)

    def test_build_in_tree_flag(self):
        """Test -I/--in-tree flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-I'])
        self.assertTrue(args.in_tree)

    def test_build_trace_flag(self):
        """Test -T/--trace flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-T'])
        self.assertTrue(args.trace)

    def test_get_build_dir(self):
        """Test get_build_dir function"""
        with mock.patch.object(settings, 'get', return_value='/tmp/b'):
            result = build.get_build_dir('sandbox')
        self.assertEqual('/tmp/b/sandbox', result)

    def test_get_build_dir_custom(self):
        """Test get_build_dir with custom directory"""
        with mock.patch.object(settings, 'get', return_value='/custom/build'):
            result = build.get_build_dir('snow')
        self.assertEqual('/custom/build/snow', result)
