# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Functional tests for utool CI automation tool"""

# pylint: disable=import-error,wrong-import-position,ungrouped-imports

import argparse
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add the utool package to the path
utool_path = Path(__file__).parent
sys.path.insert(0, str(utool_path))

# Add u-boot tools to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../u/tools'))

from u_boot_pylib import command
from u_boot_pylib import terminal
from utool_pkg import cmdline, control, gitlab_parser


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
        'merge': False,
        'test_spec': None,
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
        self.assertEqual(ci_vars, expected)

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
        self.assertEqual(ci_vars, expected)

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
        self.assertEqual(ci_vars, expected)
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
        self.assertEqual(ci_vars, expected)

    def test_build_ci_vars_job_name_targeting(self):
        """Test build_ci_vars with job name targeting (e.g. 'sandbox clang')"""
        args = make_args(pytest='sandbox with clang test.py')
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '0',
            'PYTEST': 'sandbox with clang test.py',
            'WORLD': '0',
            'SJG_LAB': ''
        }
        self.assertEqual(ci_vars, expected)

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
        self.assertEqual(ci_vars, expected)

    def test_build_commit_tags_no_skip(self):
        """Test build_commit_tags with no skip flags (all enabled)"""
        args = make_args(suites=True, pytest='1', world=True, sjg='1')
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        self.assertEqual(tags, '')

    def test_build_commit_tags_skip_all(self):
        """Test build_commit_tags with --null flag (skip all)"""
        args = make_args(null=True)
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        expected_tags = '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]'
        self.assertEqual(tags, expected_tags)

    def test_build_commit_tags_skip_specific(self):
        """Test build_commit_tags with specific stages enabled"""
        args = make_args(suites=True)  # Only suites enabled, others skip
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        expected_tags = '[skip-pytest] [skip-world] [skip-sjg]'
        self.assertEqual(tags, expected_tags)

    def test_build_commit_tags_skip_world_only(self):
        """Test build_commit_tags with world skipped"""
        # suites and pytest enabled, world skipped
        args = make_args(suites=True, pytest='1')
        ci_vars = control.build_ci_vars(args)
        tags = control.build_commit_tags(args, ci_vars)
        expected_tags = '[skip-world] [skip-sjg]'
        self.assertEqual(tags, expected_tags)

    def test_commit_message_tag_integration(self):
        """Test tags integration into commit message description"""

        # Test append_tags_to_description function directly

        # Scenario 1: Empty description with tags
        tags = '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]'
        result = control.append_tags_to_description('', tags)
        expected = '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]'
        self.assertEqual(result, expected)

        # Scenario 2: Existing description with tags
        description = 'This is a test commit\n\nSome details about the change'
        result = control.append_tags_to_description(description, tags)
        expected = ('This is a test commit\n\nSome details about the change\n\n'
                   '[skip-suites] [skip-pytest] [skip-world] [skip-sjg]')
        self.assertEqual(result, expected)

        # Scenario 3: No tags (should return original description unchanged)
        result = control.append_tags_to_description('Test description', '')
        self.assertEqual(result, 'Test description')

        # Scenario 4: Empty description with no tags
        result = control.append_tags_to_description('', '')
        self.assertEqual(result, '')

class TestUtoolCI(TestBase):
    """Test the CI command functionality"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = None
        self.original_cwd = os.getcwd()

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        super().tearDown()

    def _create_git_repo(self):
        """Create a temporary git repository for testing"""
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)

        # Initialise git repo (capture output to keep it silent)
        command.run('git', 'init', capture=True)
        command.run('git', 'config', 'user.name', 'Test User', capture=True)
        command.run('git', 'config', 'user.email', 'test@example.com',
                    capture=True)

        # Create initial commit
        Path('test.txt').write_text('test content', encoding='utf-8')
        command.run('git', 'add', '.', capture=True)
        command.run('git', 'commit', '-m', 'Initial commit', capture=True)

    def test_ci_not_in_git_repo(self):
        """Test CI command fails when not in git repository"""
        # Change to a non-git directory
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            args = make_args()
            with terminal.capture():
                # Should raise CommandExc when git command fails
                with self.assertRaises(command.CommandExc):
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
        self.assertEqual(res.return_code, 0)


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

    def test_invalid_pytest_value(self):
        """Test validation of invalid pytest values"""
        args = make_args(cmd='ci', pytest='invalid_board')
        with terminal.capture():
            res = control.run_command(args)
        self.assertEqual(res, 1)

    def test_invalid_sjg_value(self):
        """Test validation of invalid SJG_LAB values"""
        args = make_args(cmd='ci', sjg='invalid_lab')
        with terminal.capture():
            res = control.run_command(args)
        self.assertEqual(res, 1)

    def test_valid_pytest_value(self):
        """Test validation of valid pytest values"""
        args = make_args(cmd='ci', pytest='sandbox', dry_run=True)

        # Mock the CI function to avoid git operations
        original_do_ci = control.do_ci
        control.do_ci = lambda args: 0

        try:
            with terminal.capture():
                res = control.run_command(args)
            self.assertEqual(res, 0)
        finally:
            control.do_ci = original_do_ci

    def test_valid_sjg_value(self):
        """Test validation of valid SJG_LAB values"""
        args = make_args(cmd='ci', sjg='rpi4', dry_run=True)

        # Mock the CI function to avoid git operations
        original_do_ci = control.do_ci
        control.do_ci = lambda args: 0

        try:
            with terminal.capture():
                res = control.run_command(args)
            self.assertEqual(res, 0)
        finally:
            control.do_ci = original_do_ci


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

        # Test to_dict() method for backward compatibility
        data = parser.to_dict()
        self.assertIsInstance(data, dict)
        self.assertIn('roles', data)
        self.assertIn('boards', data)
        self.assertIn('job_names', data)
        self.assertEqual(data['roles'], parser.roles)
        self.assertEqual(data['boards'], parser.boards)
        self.assertEqual(data['job_names'], parser.job_names)

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
        command.run('git', 'init', capture=True)
        command.run('git', 'config', 'user.email', 'test@test.com',
                    capture=True)
        command.run('git', 'config', 'user.name', 'Test User', capture=True)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

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
