# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Functional tests for utool CI automation tool"""

# pylint: disable=import-error

import argparse
import os
import shutil
import tempfile
import unittest

from u_boot_pylib import command
from u_boot_pylib import terminal
from u_boot_pylib import tools
from u_boot_pylib import tout
from utool_pkg import cmdline, control, gitlab_parser, settings

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
        'test_spec': None,
        'dest': None,
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
        tools.write_file('test.txt', 'test content', binary=False)
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
        """Test exec_cmd in dry-run mode"""
        args = make_args(dry_run=True, verbose=False)
        with terminal.capture() as (out, err):
            res = control.exec_cmd(['echo', 'test'], args)
        self.assertIsNone(res)
        self.assertFalse(out.getvalue())
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


class TestUtoolControl(TestBase):
    """Test the control module functionality"""

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
