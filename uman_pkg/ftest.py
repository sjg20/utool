# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Functional tests for uman CI automation tool"""

# pylint: disable=import-error,too-many-lines

import argparse
import ast
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from u_boot_pylib import command
from u_boot_pylib import terminal
from u_boot_pylib import tools
from u_boot_pylib import tout
import gitlab

from uman_pkg import (build, cmdconfig, cmdline, cmdpy, cmdtest, control,
                      gitlab_parser, settings, setup, util)

# Capture stdout and stderr for silent command execution
CAPTURE = {'capture': True, 'capture_stderr': True}


class TestBase(unittest.TestCase):
    """Base class for all uman tests"""
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

    def setUp(self):
        """Set up test fixtures"""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up and restore command.TEST_RESULT after each test"""
        command.TEST_RESULT = None
        if self.test_dir and os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)


def make_args(**kwargs):
    """Create an argparse.Namespace with default CI arguments"""
    defaults = {
        'all': False,
        'bisect': None,
        'board': None,
        'build': False,
        'build_dir': None,
        'c_test': False,
        'cmd': 'ci',
        'debug': False,
        'dest': None,
        'dry_run': False,
        'exitfirst': False,
        'extra_args': [],
        'find': None,
        'force': False,
        'full': False,
        'gdb': False,
        'gdbserver': None,
        'list_boards': False,
        'lto': False,
        'merge': False,
        'no_timeout': False,
        'null': False,
        'persist': False,
        'pollute': None,
        'pytest': None,
        'quiet': False,
        'setup_only': False,
        'show_cmd': False,
        'show_output': False,
        'sjg': None,
        'suites': False,
        'test_spec': [],
        'timing': None,
        'verbose': False,
        'world': False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestUmanCmdline(TestBase):
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

    def test_selftest_subcommand_parsing(self):
        """Test that selftest subcommand is parsed correctly"""
        parser = cmdline.setup_parser()

        # Test basic selftest command
        args = parser.parse_args(['selftest'])
        self.assertEqual('selftest', args.cmd)
        self.assertIsNone(args.testname)

        # Test selftest with test name
        args = parser.parse_args(['selftest', 'test_ci'])
        self.assertEqual('selftest', args.cmd)
        self.assertEqual('test_ci', args.testname)

        # Test selftest with flags
        args = parser.parse_args(['selftest', '-N', '-X'])
        self.assertTrue(args.no_capture)
        self.assertTrue(args.test_preserve_dirs)

        # Test selftest alias (use cmdline.parse_args for alias resolution)
        args = cmdline.parse_args(['st'])
        self.assertEqual(args.cmd, 'selftest')

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
        self.assertFalse(args.no_timeout)

        # Test pytest with board specified
        args = parser.parse_args(['pytest', '-B', 'sandbox', 'test_dm'])
        self.assertEqual(args.test_spec, ['test_dm'])
        self.assertEqual(args.board, 'sandbox')

        # Test pytest with multi-word test spec (no quotes needed)
        args = parser.parse_args(['pytest', '-B', 'coreboot', 'not', 'sleep'])
        self.assertEqual(args.test_spec, ['not', 'sleep'])
        self.assertEqual(args.board, 'coreboot')

        # Test pytest with --no-timeout flag
        args = parser.parse_args(['pytest', '-B', 'coreboot', 'test_dm', '-T'])
        self.assertEqual(args.board, 'coreboot')
        self.assertEqual(args.test_spec, ['test_dm'])
        self.assertTrue(args.no_timeout)

        # Test pytest alias (use cmdline.parse_args for alias resolution)
        args = cmdline.parse_args(['py', '-B', 'sandbox'])
        self.assertEqual(args.cmd, 'pytest')
        self.assertEqual(args.board, 'sandbox')

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


class TestBuildSubcommand(TestBase):  # pylint: disable=R0904
    """Test build subcommand functionality"""

    def test_get_dir(self):
        """Test build directory generation"""
        with mock.patch.object(settings, 'get', return_value='/tmp/b'):
            self.assertEqual('/tmp/b/sandbox', build.get_dir('sandbox'))

    def test_get_dir_default(self):
        """Test build directory with default when not configured"""
        with mock.patch.object(settings, 'get', return_value='/tmp/b'):
            self.assertEqual('/tmp/b/qemu-arm', build.get_dir('qemu-arm'))

    def test_get_cmd_basic(self):
        """Test basic build command generation (LTO disabled by default)"""
        args = cmdline.parse_args(['build', 'sandbox'])
        self.assertEqual(['buildman', '-L', '-I', '-w', '--boards', 'sandbox',
                          '-o', '/tmp/b/sandbox'],
                         build.get_cmd(args, 'sandbox', '/tmp/b/sandbox'))

    def test_run_no_board(self):
        """Test that run requires a board"""
        args = cmdline.parse_args(['build'])
        # Clear any $b environment variable
        with mock.patch.dict(os.environ, {}, clear=True):
            with terminal.capture():
                result = build.run(args)
        self.assertEqual(1, result)

    def test_run_dry_run(self):
        """Test build dry-run returns the correct command"""
        args = cmdline.parse_args(['-n', 'build', 'sandbox'])
        got_cmd = None

        def mock_exec_cmd(cmd, dry_run=False, env=None, capture=True):
            nonlocal got_cmd

            del dry_run, env, capture  # unused
            got_cmd = cmd

        with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
            with mock.patch.object(build, 'setup_uboot_dir',
                                   return_value='/tmp'):
                with terminal.capture():
                    result = build.run(args)
        self.assertEqual(0, result)
        self.assertIn('buildman', got_cmd)

    def test_build_lto_flag(self):
        """Test -L/--lto flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-L'])
        self.assertTrue(args.lto)

        args = cmdline.parse_args(['build', 'sandbox', '--lto'])
        self.assertTrue(args.lto)

    def test_get_cmd_lto_default(self):
        """Test that -L is passed to buildman by default (LTO disabled)"""
        args = cmdline.parse_args(['build', 'sandbox'])
        self.assertIn('-L', build.get_cmd(args, 'sandbox', '/tmp/b/sandbox'))

    def test_get_cmd_lto_enabled(self):
        """Test that -L is not passed when --lto is specified"""
        args = cmdline.parse_args(['build', 'sandbox', '-L'])
        self.assertNotIn('-L', build.get_cmd(args, 'sandbox', '/tmp/b/sandbox'))

    def test_build_board_lto_default(self):
        """Test that build_board() passes -L by default (LTO disabled)"""
        cap = []

        def mock_exec_cmd(cmd, *args, **kwargs):
            cap.append(cmd)
            return command.CommandResult(return_code=0)

        with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
            with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
                with terminal.capture():
                    build.build_board('sandbox')

        self.assertIn('-L', cap[0])

    def test_build_board_lto_enabled(self):
        """Test that build_board() omits -L when lto=True"""
        cap = []

        def mock_exec_cmd(cmd, *args, **kwargs):
            cap.append(cmd)
            return command.CommandResult(return_code=0)

        with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
            with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
                with terminal.capture():
                    build.build_board('sandbox', lto=True)

        self.assertNotIn('-L', cap[0])

    def test_build_fresh_flag(self):
        """Test -F/--fresh flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-F'])
        self.assertTrue(args.fresh)

    def test_build_target_option(self):
        """Test -t/--target option"""
        args = cmdline.parse_args(['build', 'sandbox', '-t', 'u-boot.bin'])
        self.assertEqual('u-boot.bin', args.target)

    def test_get_cmd_target(self):
        """Test that --target is passed to buildman"""
        args = cmdline.parse_args(['build', 'sandbox', '-t', 'u-boot.bin'])
        cmd = build.get_cmd(args, 'sandbox', '/tmp/b/sandbox')
        self.assertIn('--target', cmd)
        self.assertIn('u-boot.bin', cmd)

    def test_build_jobs_option(self):
        """Test -j/--jobs option"""
        args = cmdline.parse_args(['build', 'sandbox', '-j', '8'])
        self.assertEqual(8, args.jobs)

    def test_get_cmd_jobs(self):
        """Test that -j is passed to buildman"""
        args = cmdline.parse_args(['build', 'sandbox', '-j', '4'])
        cmd = build.get_cmd(args, 'sandbox', '/tmp/b/sandbox')
        self.assertIn('-j', cmd)
        self.assertIn('4', cmd)

    def test_build_objdump_flag(self):
        """Test -O/--objdump flag"""
        args = cmdline.parse_args(['build', 'sandbox', '-O'])
        self.assertTrue(args.objdump)

        args = cmdline.parse_args(['build', 'sandbox', '--objdump'])
        self.assertTrue(args.objdump)

    def test_get_execs(self):
        """Test get_execs yields existing ELF files"""
        uboot_path = os.path.join(self.test_dir, 'u-boot')
        tools.write_file(uboot_path, b'ELF')
        self.assertEqual([uboot_path], list(build.get_execs(self.test_dir)))

    def test_get_execs_empty(self):
        """Test get_execs with no ELF files"""
        self.assertEqual([], list(build.get_execs(self.test_dir)))

    def test_build_size_flag(self):
        """Test -s/--size flag"""
        args = cmdline.parse_args(['build', 'sandbox'])
        self.assertFalse(args.size)

        args = cmdline.parse_args(['build', 'sandbox', '-s'])
        self.assertTrue(args.size)

        args = cmdline.parse_args(['build', 'sandbox', '--size'])
        self.assertTrue(args.size)

    def test_build_force_reconfig_flag(self):
        """Test -f/--force-reconfig flag passes -C to buildman"""
        args = cmdline.parse_args(['build', 'sandbox', '-f'])
        self.assertTrue(args.force_reconfig)
        cmd = build.get_cmd(args, 'sandbox', '/tmp/b/sandbox')
        self.assertIn('-C', cmd)

    def test_build_in_tree_flag(self):
        """Test -I/--in-tree flag uses -i for buildman"""
        args = cmdline.parse_args(['build', 'sandbox', '-I'])
        self.assertTrue(args.in_tree)
        cmd = build.get_cmd(args, 'sandbox', '/tmp/b/sandbox')
        self.assertIn('-i', cmd)
        self.assertNotIn('-I', cmd)
        self.assertNotIn('-o', cmd)  # No output directory for in-tree

    def test_build_trace_flag(self):
        """Test -T/--trace flag sets FTRACE environment variable"""
        args = cmdline.parse_args(['build', 'sandbox', '-T'])
        self.assertTrue(args.trace)

        # Test that FTRACE is set in environment when trace flag is used
        captured_env = {}

        def mock_exec_cmd(_cmd, dry_run=False, env=None, capture=True):
            del dry_run, capture  # unused
            if env:
                captured_env.update(env)

        with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
            with mock.patch.object(build, 'setup_uboot_dir',
                                   return_value='/tmp'):
                with terminal.capture():
                    build.run(args)

        self.assertIn('FTRACE', captured_env)
        self.assertEqual('1', captured_env.get('FTRACE'))

    def test_build_gprof_flag(self):
        """Test --gprof flag sets GPROF environment variable"""
        args = cmdline.parse_args(['build', 'sandbox', '--gprof'])
        self.assertTrue(args.gprof)

        # Test that GPROF is set in environment when gprof flag is used
        captured_env = {}

        def mock_exec_cmd(_cmd, dry_run=False, env=None, capture=True):
            del dry_run, capture  # unused
            if env:
                captured_env.update(env)

        with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
            with mock.patch.object(build, 'setup_uboot_dir',
                                   return_value='/tmp'):
                with terminal.capture():
                    build.run(args)

        self.assertIn('GPROF', captured_env)
        self.assertEqual('1', captured_env.get('GPROF'))

    def test_build_output_dir_flag(self):
        """Test -o/--output-dir flag overrides build directory"""
        args = cmdline.parse_args(['build', 'sandbox', '-o', '/custom/out'])
        self.assertEqual('/custom/out', args.output_dir)

        # Test that the output directory is used in the build command
        captured_cmd = []

        def mock_exec_cmd(cmd, dry_run=False, env=None, capture=True):
            del dry_run, env, capture  # unused
            captured_cmd.extend(cmd)

        with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
            with mock.patch.object(build, 'setup_uboot_dir',
                                   return_value='/tmp'):
                with terminal.capture():
                    build.run(args)

        # Check that buildman was called with the custom output directory
        self.assertIn('-o', captured_cmd)
        idx = captured_cmd.index('-o')
        self.assertEqual('/custom/out', captured_cmd[idx + 1])

    def test_do_bisect(self):
        """Test build bisect finds first bad commit"""
        git_calls = []
        # Simulate: HEAD bad, upstream good, bisect finds mid222 as first bad
        current_commit = ['abc123']
        bisect_step = [0]

        def mock_run_one(*args, capture=False):
            del capture
            git_calls.append(args)
            result = mock.Mock()
            result.stdout = ''
            if args[1] == 'status':
                result.stdout = 'On branch my-branch'
            elif args[1] == 'checkout':
                current_commit[0] = args[2][:6]
            elif args[1] == 'bisect':
                if args[2] == 'start':
                    pass
                elif args[2] in ('good', 'bad'):
                    if len(args) == 3:  # bisect good/bad without commit
                        bisect_step[0] += 1
                        if bisect_step[0] == 1:
                            current_commit[0] = 'mid111'
                        elif bisect_step[0] == 2:
                            # Bisect complete
                            result.stdout = 'mid222abc is the first bad commit\n'
            return result

        def mock_output_one_line(*args):
            if args[1] == 'rev-parse':
                if args[2] == '@{u}':
                    return 'def456'
                return current_commit[0]
            if args[1] == 'symbolic-ref':
                return 'my-branch'
            if args[1] == 'log':
                return 'Bad commit message'
            return ''

        def mock_try_build(_board, _build_dir):
            # HEAD (abc123) bad, upstream (def456) good, mid111 bad
            return current_commit[0] == 'def456'

        tout.init(tout.NOTICE)
        with mock.patch.object(command, 'run_one', mock_run_one):
            with mock.patch.object(command, 'output_one_line',
                                   mock_output_one_line):
                with mock.patch.object(build, 'try_build', mock_try_build):
                    with terminal.capture() as (out, _err):
                        result = build.do_bisect('sandbox', '/tmp/b/sandbox')

        self.assertEqual(0, result)
        self.assertIn('First bad commit: mid222abc', out.getvalue())
        # Verify we returned to original branch
        self.assertEqual(('git', 'checkout', 'my-branch'), git_calls[-1])

    def test_do_bisect_rebase_in_progress(self):
        """Test bisect refuses to start during rebase"""
        def mock_run_one(*args, capture=False):
            del capture
            result = mock.Mock()
            result.stdout = 'interactive rebase in progress'
            return result

        tout.init(tout.WARNING)
        with mock.patch.object(command, 'run_one', mock_run_one):
            with terminal.capture() as (out, err):
                result = build.do_bisect('sandbox', '/tmp/b/sandbox')

        self.assertEqual(1, result)
        self.assertIn('Rebase in progress', err.getvalue())

    def test_build_shows_stderr_on_failure(self):
        """Test build run() shows stderr when build fails"""
        def mock_exec_cmd(cmd, dry_run=False, env=None, capture=True):
            del cmd, dry_run, env, capture
            return command.CommandResult(
                return_code=2, stdout='', stderr='error: something failed\n')

        args = cmdline.parse_args(['build', 'sandbox'])
        with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
            with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
                with terminal.capture() as (_, err):
                    result = build.run(args)

        self.assertEqual(2, result)
        self.assertIn('something failed', err.getvalue())

    def test_build_board_shows_stderr_on_failure(self):
        """Test build_board() shows stderr when build fails"""
        def mock_exec_cmd(cmd, dry_run=False, env=None, capture=True):
            del cmd, dry_run, env, capture
            return command.CommandResult(
                return_code=1, stdout='', stderr='make: *** Error 1\n')

        with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
            with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
                with terminal.capture() as (_, err):
                    result = build.build_board('sandbox')

        self.assertFalse(result)
        self.assertIn('Error 1', err.getvalue())


class TestConfigSubcommand(TestBase):
    """Test config subcommand"""

    def setUp(self):
        super().setUp()
        tout.init(tout.WARNING)
        self.build_dir = os.path.join(self.test_dir, 'sandbox')
        os.makedirs(self.build_dir)

        # Create a sample .config file
        config_content = """#
# Automatically generated file
#
CONFIG_SANDBOX=y
CONFIG_SYS_ARCH="sandbox"
CONFIG_VIDEO=y
# CONFIG_VIDEO_FONT_4X6 is not set
CONFIG_DM_TEST=y
"""
        with open(os.path.join(self.build_dir, '.config'), 'w') as outf:
            outf.write(config_content)

    def test_config_subcommand_parsing(self):
        """Test config subcommand argument parsing"""
        args = cmdline.parse_args(['config', '-B', 'sandbox', '-g', 'VIDEO'])
        self.assertEqual('config', args.cmd)
        self.assertEqual('sandbox', args.board)
        self.assertEqual('VIDEO', args.grep)

    def test_config_alias(self):
        """Test cfg alias works"""
        args = cmdline.parse_args(['cfg', '-B', 'sandbox', '-g', 'TEST'])
        self.assertEqual('config', args.cmd)

    def test_config_grep(self):
        """Test config grep finds matches"""
        args = cmdline.parse_args(['config', '-B', 'sandbox', '-g', 'VIDEO',
                                   '--build-dir', self.build_dir])
        with terminal.capture() as (out, _):
            ret = cmdconfig.run(args)
        self.assertEqual(0, ret)
        self.assertIn('CONFIG_VIDEO=y', out.getvalue())
        self.assertIn('VIDEO_FONT', out.getvalue())

    def test_config_grep_case_insensitive(self):
        """Test config grep is case-insensitive"""
        args = cmdline.parse_args(['config', '-B', 'sandbox', '-g', 'video',
                                   '--build-dir', self.build_dir])
        with terminal.capture() as (out, _):
            ret = cmdconfig.run(args)
        self.assertEqual(0, ret)
        self.assertIn('CONFIG_VIDEO=y', out.getvalue())

    def test_config_grep_no_match(self):
        """Test config grep with no matches"""
        args = cmdline.parse_args(['config', '-B', 'sandbox', '-g', 'NONEXISTENT',
                                   '--build-dir', self.build_dir])
        with terminal.capture() as (out, _):
            ret = cmdconfig.run(args)
        self.assertEqual(0, ret)
        self.assertFalse(out.getvalue())

    def test_config_no_board(self):
        """Test config fails without board"""
        orig_b = os.environ.pop('b', None)
        try:
            args = cmdline.parse_args(['config', '-g', 'VIDEO'])
            with terminal.capture() as (_, err):
                ret = cmdconfig.run(args)
            self.assertEqual(1, ret)
            self.assertIn('Board is required', err.getvalue())
        finally:
            if orig_b:
                os.environ['b'] = orig_b

    def test_config_no_action(self):
        """Test config fails without action"""
        args = cmdline.parse_args(['config', '-B', 'sandbox'])
        with terminal.capture() as (_, err):
            ret = cmdconfig.run(args)
        self.assertEqual(1, ret)
        self.assertIn('No action specified', err.getvalue())

    def test_config_missing_config_file(self):
        """Test config fails when .config not found"""
        args = cmdline.parse_args(['config', '-B', 'sandbox', '-g', 'VIDEO',
                                   '--build-dir', '/nonexistent/path'])
        with terminal.capture() as (_, err):
            ret = cmdconfig.run(args)
        self.assertEqual(1, ret)
        self.assertIn('Config file not found', err.getvalue())


class TestUmanCIVars(TestBase):
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

    def test_build_ci_vars_all_flag(self):
        """Test build_ci_vars with -a flag (all stages including lab)"""
        args = make_args(all=True)
        ci_vars = control.build_ci_vars(args)
        expected = {
            'SUITES': '1',
            'PYTEST': '1',
            'WORLD': '1',
            'SJG_LAB': '1'
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

class TestUmanCI(TestBase):
    """Test the CI command functionality"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.orig_cwd = os.getcwd()
        tout.init(tout.NOTICE)

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.orig_cwd)
        super().tearDown()

    def _create_git_repo(self):
        """Create a temporary git repository for testing"""
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
        with terminal.capture() as (out, err):
            res = control.exec_cmd(['echo', 'test'], dry_run=True)
        self.assertIsNone(res)
        self.assertEqual('echo test\n', out.getvalue())
        self.assertFalse(err.getvalue())

    def test_exec_cmd_normal(self):
        """Test exec_cmd in normal mode"""
        with terminal.capture() as (out, err):
            res = control.exec_cmd(['true'], dry_run=False)
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


class TestUmanControl(TestBase):  # pylint: disable=too-many-public-methods
    """Test the control module functionality"""

    def setUp(self):
        """Set up test environment with fake U-Boot tree"""
        super().setUp()
        self.empty_dir = tempfile.mkdtemp()  # Empty dir (not a U-Boot tree)
        self.orig_cwd = os.getcwd()
        self.orig_usrc = os.environ.get('USRC')
        if 'USRC' in os.environ:
            del os.environ['USRC']
        os.chdir(self.test_dir)
        os.makedirs('test/py')
        tools.write_file('test/py/test.py', b'# test')

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.orig_cwd)
        if self.orig_usrc is not None:
            os.environ['USRC'] = self.orig_usrc
        elif 'USRC' in os.environ:
            del os.environ['USRC']
        shutil.rmtree(self.empty_dir)
        super().tearDown()

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

        def mock_subprocess_run(cmd, **_kwargs):
            cap.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        # Test basic pytest command
        args = make_args(cmd='pytest', board='sandbox')
        with mock.patch('subprocess.run', mock_subprocess_run):
            with terminal.capture():
                res = control.run_command(args)
        self.assertEqual(0, res)

        # Verify command structure
        cmd = cap[-1]
        self.assertTrue(cmd[0].endswith('/test/py/test.py'))
        self.assertIn('-B', cmd)
        self.assertIn('sandbox', cmd)
        # Default should not add --no-timeout
        self.assertNotIn('--no-timeout', cmd)

        # Test pytest with --no-timeout flag
        args = make_args(cmd='pytest', board='malta', test_spec=['test_dm'],
                         no_timeout=True)
        with mock.patch('subprocess.run', mock_subprocess_run):
            with terminal.capture():
                res = control.run_command(args)
        self.assertEqual(0, res)

        cmd = cap[-1]
        self.assertIn('malta', cmd)
        self.assertIn('-k', cmd)
        self.assertIn('test_dm', cmd)
        self.assertIn('--no-timeout', cmd)

    def test_pytest_extra_args(self):
        """Test pytest command with extra arguments after --"""
        cap = []

        def mock_subprocess_run(cmd, **_kwargs):
            cap.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        # Test extra args parsing through cmdline
        args = cmdline.parse_args(['py', '-B', 'sandbox', 'TestFsBasic',
                                   '--', '--fs-type', 'ext4'])
        self.assertEqual(['TestFsBasic'], args.test_spec)
        self.assertEqual(['--fs-type', 'ext4'], args.extra_args)

        # Test command building includes extra args
        with mock.patch('subprocess.run', mock_subprocess_run):
            with terminal.capture():
                res = control.run_command(args)
        self.assertEqual(0, res)

        cmd = cap[-1]
        self.assertIn('--fs-type', cmd)
        self.assertIn('ext4', cmd)

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
        orig_b = os.environ.pop('b', None)
        try:
            args = make_args(cmd='pytest', board=None)
            with terminal.capture() as (_, err):
                res = control.run_command(args)
            self.assertEqual(1, res)
            self.assertIn('Board is required', err.getvalue())
        finally:
            if orig_b is not None:
                os.environ['b'] = orig_b

    def test_pytest_board_from_env(self):
        """Test that pytest uses $b environment variable"""
        cap = []

        def mock_subprocess_run(cmd, **_kwargs):
            cap.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        orig_env = os.environ.get('b')

        try:
            os.environ['b'] = 'sandbox'
            args = make_args(cmd='pytest', board=None)
            with mock.patch('subprocess.run', mock_subprocess_run):
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

        def mock_subprocess_run(cmd, **_kwargs):
            cap.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        args = make_args(cmd='pytest', board='sandbox', quiet=True)
        with mock.patch('subprocess.run', mock_subprocess_run):
            with terminal.capture():
                res = control.run_command(args)
        self.assertEqual(0, res)

        cmd = cap[-1]
        self.assertIn('--no-header', cmd)
        self.assertIn('--quiet-hooks', cmd)

    def test_pytest_no_full_unsupported(self):
        """Test do_pytest detects --no-full not supported"""

        def mock_subprocess_run(cmd, **_kwargs):
            return subprocess.CompletedProcess(
                cmd, 4, stderr=b'error: unrecognized arguments: --no-full')

        args = make_args(cmd='pytest', board='sandbox')
        with mock.patch('subprocess.run', mock_subprocess_run):
            with terminal.capture() as (_, err):
                res = control.run_command(args)
        self.assertEqual(4, res)
        self.assertIn('--no-full', err.getvalue())
        self.assertIn('use -f', err.getvalue())

    def test_pytest_lto_flag(self):
        """Test -L/--lto flag for pytest"""
        args = cmdline.parse_args(['pytest', '-B', 'sandbox', '-L'])
        self.assertTrue(args.lto)

        args = cmdline.parse_args(['pytest', '-B', 'sandbox', '--lto'])
        self.assertTrue(args.lto)

    def test_pytest_lto_with_build(self):
        """Test that -L with -b passes lto to build_board()"""
        cap = []

        def mock_exec_cmd(cmd, *args, **kwargs):
            cap.append(cmd)
            return command.CommandResult(return_code=0)

        def mock_subprocess_run(cmd, **_kwargs):
            cap.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        args = make_args(cmd='pytest', board='sandbox', build=True, lto=True)
        with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
            with mock.patch.object(build, 'exec_cmd', mock_exec_cmd):
                with mock.patch('subprocess.run', mock_subprocess_run):
                    with terminal.capture():
                        control.run_command(args)

        # First command should be buildman without -L (LTO enabled)
        self.assertNotIn('-L', cap[0])

    def test_pytest_find_flag(self):
        """Test -F/--find flag for pytest"""
        args = cmdline.parse_args(['pytest', '-B', 'sandbox', '-F', 'video'])
        self.assertEqual('video', args.find)

        args = cmdline.parse_args(['pytest', '-B', 'sandbox', '--find', 'dm'])
        self.assertEqual('dm', args.find)

    def test_pytest_find_tests(self):
        """Test finding tests with -F option"""
        def mock_collect(**_kwargs):
            return command.CommandResult(
                stdout='test_ut.py::TestUt::test_dm_video\n'
                       'test_ut.py::TestUt::test_dm_gpio\n'
                       'test_ut.py::TestUt::test_fs_fat\n',
                return_code=0)

        command.TEST_RESULT = mock_collect

        args = make_args(cmd='pytest', board='sandbox', find='video')
        with terminal.capture() as (out, _):
            res = control.run_command(args)
        self.assertEqual(0, res)
        self.assertIn('test_dm_video', out.getvalue())
        self.assertNotIn('test_dm_gpio', out.getvalue())

    def test_pytest_find_no_match(self):
        """Test -F with no matching tests"""
        def mock_collect(**_kwargs):
            return command.CommandResult(
                stdout='test_ut.py::TestUt::test_dm_gpio\n',
                return_code=0)

        command.TEST_RESULT = mock_collect

        args = make_args(cmd='pytest', board='sandbox', find='nonexistent')
        with terminal.capture() as (_, err):
            res = control.run_command(args)
        self.assertEqual(1, res)
        self.assertIn("No tests matching 'nonexistent'", err.getvalue())

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
        self.assertEqual(self.test_dir, util.get_uboot_dir())

    def test_get_uboot_dir_usrc_env(self):
        """Test get_uboot_dir uses $USRC when not in U-Boot tree"""
        os.chdir(self.empty_dir)
        os.environ['USRC'] = self.test_dir
        self.assertEqual(self.test_dir, util.get_uboot_dir())

    def test_get_uboot_dir_not_found(self):
        """Test get_uboot_dir returns None when no U-Boot tree found"""
        os.chdir(self.empty_dir)
        self.assertIsNone(util.get_uboot_dir())

    def test_setup_uboot_dir_current(self):
        """Test setup_uboot_dir when already in U-Boot tree"""
        # setUp already created fake U-Boot tree in self.test_dir
        result = util.setup_uboot_dir()
        self.assertEqual(self.test_dir, result)
        self.assertEqual(self.test_dir, os.getcwd())

    def test_setup_uboot_dir_changes_dir(self):
        """Test setup_uboot_dir changes to $USRC directory"""
        os.chdir(self.empty_dir)
        os.environ['USRC'] = self.test_dir

        with terminal.capture():
            result = util.setup_uboot_dir()

        self.assertEqual(self.test_dir, result)
        self.assertEqual(self.test_dir, os.getcwd())

    def test_setup_uboot_dir_not_found(self):
        """Test setup_uboot_dir returns None when no U-Boot tree"""
        os.chdir(self.empty_dir)
        with terminal.capture():
            result = util.setup_uboot_dir()

        self.assertIsNone(result)

    def test_pytest_not_in_uboot_tree(self):
        """Test pytest fails when not in U-Boot tree and no $USRC"""
        os.chdir(self.empty_dir)
        args = make_args(cmd='pytest', board='sandbox')
        with terminal.capture() as (_, err):
            res = control.run_command(args)
        self.assertEqual(1, res)
        self.assertIn('Not in a U-Boot tree', err.getvalue())

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

    @mock.patch('uman_pkg.cmdpy.settings')
    @mock.patch('uman_pkg.cmdpy.socket')
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

    @mock.patch('uman_pkg.cmdpy.settings')
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


class TestUmanMergeRequest(TestBase):
    """Tests for merge request functionality"""

    def setUp(self):
        super().setUp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        # Initialize git repo
        command.run('git', 'init', **CAPTURE)
        command.run('git', 'config', 'user.email', 'test@test.com', **CAPTURE)
        command.run('git', 'config', 'user.name', 'Test User', **CAPTURE)

    def tearDown(self):
        os.chdir(self.old_cwd)
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

    @mock.patch('pickman.gitlab_api', create=True)
    @mock.patch('uman_pkg.control.gitlab')
    @mock.patch('uman_pkg.control.extract_mr_info')
    @mock.patch('uman_pkg.control.gitutil')
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

    @mock.patch('pickman.gitlab_api', create=True)
    @mock.patch('uman_pkg.control.gitlab')
    @mock.patch('uman_pkg.control.extract_mr_info')
    @mock.patch('uman_pkg.control.gitutil')
    @mock.patch('uman_pkg.control.git_push_branch')
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


class TestSettings(TestBase):
    """Tests for settings module"""

    def setUp(self):
        super().setUp()
        self.config_file = os.path.join(self.test_dir, '.uman')
        # Reset global settings state
        settings.SETTINGS['config'] = None

    def tearDown(self):
        settings.SETTINGS['config'] = None
        super().tearDown()

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
        super().setUp()
        self.orig_cwd = os.getcwd()
        tout.init(tout.NOTICE)

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.orig_cwd)
        super().tearDown()

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
        with mock.patch('uman_pkg.setup.command.output'):
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
        with mock.patch('uman_pkg.setup.command.output', mock_output):
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


class TestUtil(TestBase):
    """Tests for util module"""

    def setUp(self):
        super().setUp()
        tout.init(tout.NOTICE)

    def test_run_pytest_success(self):
        """Test run_pytest returns True on success"""
        moc = command.CommandResult(return_code=0)

        with mock.patch.object(util, 'get_uboot_dir', return_value='/uboot'):
            with mock.patch('os.chdir'):
                with mock.patch.object(util, 'exec_cmd',
                                       return_value=moc) as run:
                    result = util.run_pytest('test_foo')

        self.assertTrue(result)
        run.assert_called_once()
        cmd = run.call_args[0][0]
        self.assertEqual('./test/py/test.py', cmd[0])
        self.assertIn('--buildman', cmd)
        self.assertIn('-k', cmd)
        self.assertEqual('test_foo', cmd[cmd.index('-k') + 1])

    def test_run_pytest_failure(self):
        """Test run_pytest returns False on failure"""
        moc = command.CommandResult(return_code=1, stderr='Test failed')

        with mock.patch.object(util, 'get_uboot_dir', return_value='/uboot'):
            with mock.patch('os.chdir'):
                with mock.patch.object(util, 'exec_cmd', return_value=moc):
                    with terminal.capture():
                        result = util.run_pytest('test_foo')

        self.assertFalse(result)

    def test_run_pytest_no_uboot_dir(self):
        """Test run_pytest returns False when not in U-Boot tree"""
        with mock.patch.object(util, 'get_uboot_dir', return_value=None):
            with terminal.capture():
                result = util.run_pytest('test_foo')

        self.assertFalse(result)

    def test_run_pytest_dry_run(self):
        """Test run_pytest in dry-run mode"""
        with mock.patch.object(util, 'get_uboot_dir', return_value='/uboot'):
            with mock.patch('os.chdir'):
                with terminal.capture() as (out, _):
                    result = util.run_pytest('test_foo', dry_run=True)

        self.assertTrue(result)
        self.assertIn('test.py', out.getvalue())


class TestTestSubcommand(TestBase):  # pylint: disable=R0904
    """Tests for the test subcommand"""

    # C source with linker-list symbols matching U-Boot's unit test format
    TEST_ELF_SOURCE = """
/* Linker-list symbols: _u_boot_list_2_ut_<suite>_2_<test> */
char _u_boot_list_2_ut_dm_2_test_acpi __attribute__((used));
char _u_boot_list_2_ut_dm_2_test_gpio __attribute__((used));
char _u_boot_list_2_ut_env_2_test_env_basic __attribute__((used));
/* Suite end markers */
char suite_end_dm __attribute__((used));
char suite_end_env __attribute__((used));
int main(void) { return 0; }
"""

    def setUp(self):
        super().setUp()
        tout.init(tout.NOTICE)
        # Compile a test ELF with linker-list symbols
        self.test_elf = os.path.join(self.test_dir, 'test_elf')
        src_file = os.path.join(self.test_dir, 'test.c')
        tools.write_file(src_file, self.TEST_ELF_SOURCE.encode())
        command.run('gcc', '-o', self.test_elf, src_file)

    def test_test_subcommand_parsing(self):
        """Test that test subcommand is parsed correctly"""
        parser = cmdline.setup_parser()

        # Test basic test command
        args = parser.parse_args(['test'])
        self.assertEqual('test', args.cmd)
        self.assertEqual([], args.tests)
        self.assertFalse(args.list_tests)
        self.assertFalse(args.list_suites)
        self.assertFalse(args.full)
        self.assertFalse(args.test_verbose)

        # Test with test names
        args = parser.parse_args(['test', 'dm', 'env'])
        self.assertEqual(['dm', 'env'], args.tests)

        # Test with -l flag
        args = parser.parse_args(['test', '-l'])
        self.assertTrue(args.list_tests)

        # Test with -s flag
        args = parser.parse_args(['test', '-s'])
        self.assertTrue(args.list_suites)

        # Test with -f flag
        args = parser.parse_args(['test', '-f'])
        self.assertTrue(args.full)

        # Test with -V flag
        args = parser.parse_args(['test', '-V'])
        self.assertTrue(args.test_verbose)

        # Test with -r flag
        args = parser.parse_args(['test', '-r'])
        self.assertTrue(args.results)

    def test_test_alias(self):
        """Test that 't' alias works for test"""
        args = cmdline.parse_args(['t'])
        self.assertEqual('test', args.cmd)

        args = cmdline.parse_args(['t', 'dm'])
        self.assertEqual('test', args.cmd)
        self.assertEqual(['dm'], args.tests)

    def test_get_sandbox_path_exists(self):
        """Test get_sandbox_path when sandbox exists"""
        sandbox_path = os.path.join(self.test_dir, 'sandbox', 'u-boot')
        os.makedirs(os.path.dirname(sandbox_path))
        tools.write_file(sandbox_path, b'fake executable')
        with mock.patch.object(settings, 'get', return_value=self.test_dir):
            self.assertEqual(sandbox_path, cmdtest.get_sandbox_path())

    def test_get_sandbox_path_not_exists(self):
        """Test get_sandbox_path when sandbox does not exist"""
        with mock.patch.object(settings, 'get', return_value=self.test_dir):
            self.assertIsNone(cmdtest.get_sandbox_path())

    def test_get_suites_from_nm(self):
        """Test that suites are extracted from nm output"""
        suites = cmdtest.get_suites_from_nm(self.test_elf)
        self.assertEqual(['dm', 'env'], suites)

    def test_get_tests_from_nm_all(self):
        """Test that all tests are extracted from nm output"""
        tests = cmdtest.get_tests_from_nm(self.test_elf)
        self.assertEqual([
            ('dm', 'test_acpi'),
            ('dm', 'test_gpio'),
            ('env', 'test_env_basic'),
        ], tests)

    def test_get_tests_from_nm_filtered(self):
        """Test that tests can be filtered by suite"""
        tests = cmdtest.get_tests_from_nm(self.test_elf, suite='dm')
        self.assertEqual([('dm', 'test_acpi'), ('dm', 'test_gpio')], tests)

        tests = cmdtest.get_tests_from_nm(self.test_elf, suite='env')
        self.assertEqual([('env', 'test_env_basic')], tests)

    def test_do_test_no_sandbox(self):
        """Test do_test fails gracefully when sandbox not found"""
        args = cmdline.parse_args(['test'])
        with mock.patch.object(cmdtest, 'get_sandbox_path', return_value=None):
            with terminal.capture() as out:
                result = cmdtest.do_test(args)
        self.assertEqual(1, result)
        self.assertIn('Sandbox not found', out[1].getvalue())

    def test_do_test_list_suites(self):
        """Test -s flag lists all test suites"""
        args = cmdline.parse_args(['test', '-s'])
        with mock.patch.object(cmdtest, 'get_sandbox_path',
                               return_value=self.test_elf):
            with terminal.capture() as out:
                result = cmdtest.do_test(args)
        self.assertEqual(0, result)
        stdout = out[0].getvalue()
        self.assertIn('dm', stdout)
        self.assertIn('env', stdout)

    def test_do_test_list_tests(self):
        """Test -l flag lists all tests"""
        args = cmdline.parse_args(['test', '-l'])
        with mock.patch.object(cmdtest, 'get_sandbox_path',
                               return_value=self.test_elf):
            with terminal.capture() as out:
                result = cmdtest.do_test(args)
        self.assertEqual(0, result)
        stdout = out[0].getvalue()
        self.assertIn('dm.test_acpi', stdout)
        self.assertIn('dm.test_gpio', stdout)
        self.assertIn('env.test_env_basic', stdout)

    def test_do_test_list_tests_by_suite(self):
        """Test -l with suite name filters tests"""
        args = cmdline.parse_args(['test', '-l', 'dm'])
        with mock.patch.object(cmdtest, 'get_sandbox_path',
                               return_value=self.test_elf):
            with terminal.capture() as out:
                result = cmdtest.do_test(args)
        self.assertEqual(0, result)
        stdout = out[0].getvalue()
        self.assertIn('dm.test_acpi', stdout)
        self.assertIn('dm.test_gpio', stdout)
        self.assertNotIn('env.test_env_basic', stdout)

    def test_build_ut_cmd_no_tests(self):
        """Test build_ut_cmd with all specs"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('all', None)])
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-c', 'ut -E all'], cmd)

    def test_build_ut_cmd_full(self):
        """Test build_ut_cmd with full flag (both tree types)"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', None)],
                                   full=True)
        self.assertEqual(['/path/to/sandbox', '-T', '-c', 'ut -E dm'], cmd)

    def test_build_ut_cmd_verbose(self):
        """Test build_ut_cmd with verbose flag"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', None)],
                                   verbose=True)
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-v', '-c', 'ut -E dm'],
                         cmd)

    def test_build_ut_cmd_all_flags(self):
        """Test build_ut_cmd with all flags"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', None)],
                                   full=True, verbose=True)
        self.assertEqual(['/path/to/sandbox', '-T', '-v', '-c', 'ut -E dm'], cmd)

    def test_build_ut_cmd_suite(self):
        """Test build_ut_cmd with suite name"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', None)])
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-c', 'ut -E dm'], cmd)

    def test_build_ut_cmd_specific_test(self):
        """Test build_ut_cmd with specific test (suite.test)"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', 'test_one')])
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-c', 'ut -E dm test_one'],
                         cmd)

    def test_build_ut_cmd_multiple_tests(self):
        """Test build_ut_cmd with multiple test specifications"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox',
                                   [('dm', None), ('env', None)])
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-c',
                          'ut -E dm; ut -E env'], cmd)

    def test_build_ut_cmd_legacy(self):
        """Test build_ut_cmd with legacy flag omits -E"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', None)],
                                   legacy=True)
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-c', 'ut dm'], cmd)

    def test_build_ut_cmd_manual(self):
        """Test build_ut_cmd with manual flag"""
        cmd = cmdtest.build_ut_cmd('/path/to/sandbox', [('dm', None)],
                                   manual=True)
        self.assertEqual(['/path/to/sandbox', '-T', '-F', '-c', 'ut -E -m dm'], cmd)

    def test_run_tests_basic(self):
        """Test run_tests executes sandbox correctly"""
        cap = []

        def mock_run(*cmd_args, **_kwargs):
            cap.append(cmd_args)
            return command.CommandResult(return_code=0,
                                         stdout='Result: PASS dm_test\n')

        args = cmdline.parse_args(['test', 'dm'])
        col = terminal.Color()
        with mock.patch.object(command, 'run_one', mock_run):
            with mock.patch.object(cmdtest, 'ensure_dm_init_files',
                                   return_value=True):
                with terminal.capture():
                    result = cmdtest.run_tests('/path/to/sandbox',
                                               [('dm', None)], args, col)
        self.assertEqual(0, result)
        self.assertEqual(('/path/to/sandbox', '-T', '-F', '-c', 'ut -E dm'), cap[0])

    def test_run_tests_full(self):
        """Test run_tests with full flag (both tree types)"""
        cap = []

        def mock_run(*cmd_args, **_kwargs):
            cap.append(cmd_args)
            return command.CommandResult(return_code=0,
                                         stdout='Result: PASS dm_test\n')

        args = cmdline.parse_args(['test', '-f', 'dm'])
        col = terminal.Color()
        with mock.patch.object(command, 'run_one', mock_run):
            with mock.patch.object(cmdtest, 'ensure_dm_init_files',
                                   return_value=True):
                with terminal.capture():
                    result = cmdtest.run_tests('/path/to/sandbox',
                                               [('dm', None)], args, col)
        self.assertEqual(0, result)
        self.assertEqual(('/path/to/sandbox', '-T', '-c', 'ut -E dm'), cap[0])

    def test_run_tests_verbose(self):
        """Test run_tests with verbose flag"""
        cap = []

        def mock_run(*cmd_args, **_kwargs):
            cap.append(cmd_args)
            return command.CommandResult(return_code=0,
                                         stdout='Result: PASS dm_test\n')

        args = cmdline.parse_args(['test', '-V', 'dm'])
        col = terminal.Color()
        with mock.patch.object(command, 'run_one', mock_run):
            with mock.patch.object(cmdtest, 'ensure_dm_init_files',
                                   return_value=True):
                with terminal.capture():
                    result = cmdtest.run_tests('/path/to/sandbox',
                                               [('dm', None)], args, col)
        self.assertEqual(0, result)
        self.assertEqual(('/path/to/sandbox', '-T', '-F', '-v', '-c', 'ut -E dm'),
                         cap[0])

    def test_parse_legacy_results_all_pass(self):
        """Test parse_legacy_results with all passing tests"""
        output = '''
Test: dm_test_first ... ok
Test: dm_test_second ... ok
Test: dm_test_third ... ok
'''
        res = cmdtest.parse_legacy_results(output)
        self.assertEqual(3, res.passed)
        self.assertEqual(0, res.failed)
        self.assertEqual(0, res.skipped)

    def test_parse_legacy_results_mixed(self):
        """Test parse_legacy_results with mixed results"""
        output = '''
Test: dm_test_first ... ok
Test: dm_test_second ... FAILED
Test: dm_test_third ... SKIPPED
Test: dm_test_fourth ... ok
'''
        res = cmdtest.parse_legacy_results(output)
        self.assertEqual(2, res.passed)
        self.assertEqual(1, res.failed)
        self.assertEqual(1, res.skipped)

    def test_parse_results_legacy(self):
        """Test parse_legacy_results with old-style Test: lines"""
        output = '''
Test: dm_test_first ... ok
Test: dm_test_second ... FAILED
Test: dm_test_third ... SKIPPED
'''
        res = cmdtest.parse_legacy_results(output)
        self.assertEqual(1, res.passed)
        self.assertEqual(1, res.failed)
        self.assertEqual(1, res.skipped)

        # parse_results returns None for old-style output
        self.assertIsNone(cmdtest.parse_results(output))

    def test_parse_results_only_result_lines(self):
        """Test parse_results ignores Test: lines (only Result: lines)"""
        output = '''
Test: dm_test_first ... ok
Result: PASS dm_test_second
Test: dm_test_third ... FAILED
Result: SKIP dm_test_fourth
'''
        res = cmdtest.parse_results(output)
        self.assertEqual(1, res.passed)
        self.assertEqual(0, res.failed)
        self.assertEqual(1, res.skipped)

    def test_parse_results_empty(self):
        """Test parse_results with empty output returns None"""
        self.assertIsNone(cmdtest.parse_results(''))
        self.assertIsNone(cmdtest.parse_legacy_results(''))

    def test_parse_results_named_tuple(self):
        """Test parse_results returns TestCounts named tuple"""
        output = 'Result: PASS test1\nResult: FAIL test2\n'
        res = cmdtest.parse_results(output)
        self.assertIsInstance(res, cmdtest.TestCounts)
        self.assertEqual(1, res.passed)
        self.assertEqual(1, res.failed)
        self.assertEqual(0, res.skipped)

    def test_parse_legacy_results_show_results(self):
        """Test parse_legacy_results with show_results flag"""
        output = '''
Test: dm_test_first ... ok
Test: dm_test_second ... FAILED
Test: dm_test_third ... SKIPPED
'''
        col = terminal.Color()
        with terminal.capture() as (out, _):
            res = cmdtest.parse_legacy_results(output, show_results=True,
                                               col=col)
        self.assertEqual(1, res.passed)
        self.assertEqual(1, res.failed)
        self.assertEqual(1, res.skipped)
        stdout = out.getvalue()
        self.assertIn('PASS: dm_test_first', stdout)
        self.assertIn('FAIL: dm_test_second', stdout)
        self.assertIn('SKIP: dm_test_third', stdout)

    def test_format_duration_seconds(self):
        """Test format_duration with seconds only"""
        self.assertEqual('0.00s', cmdtest.format_duration(0))
        self.assertEqual('1.50s', cmdtest.format_duration(1.5))
        self.assertEqual('59.99s', cmdtest.format_duration(59.99))

    def test_format_duration_minutes(self):
        """Test format_duration with minutes"""
        self.assertEqual('1m 0.0s', cmdtest.format_duration(60))
        self.assertEqual('1m 30.0s', cmdtest.format_duration(90))
        self.assertEqual('5m 30.5s', cmdtest.format_duration(330.5))

    def test_run_tests_shows_summary(self):
        """Test run_tests shows results summary"""
        output = '''
Result: PASS dm_test_first
Result: PASS dm_test_second
'''

        def mock_run(*_args, **_kwargs):
            return command.CommandResult(return_code=0, stdout=output)

        args = cmdline.parse_args(['test', 'dm'])
        col = terminal.Color()
        with mock.patch.object(command, 'run_one', mock_run):
            with mock.patch.object(cmdtest, 'ensure_dm_init_files',
                                   return_value=True):
                with terminal.capture() as (out, err):
                    result = cmdtest.run_tests('/path/to/sandbox',
                                               [('dm', None)], args, col)
        self.assertEqual(0, result)
        self.assertFalse(err.getvalue())
        stdout = out.getvalue()
        self.assertIn('2 passed', stdout)
        self.assertIn('0 failed', stdout)

    def test_run_tests_shows_output_when_no_results(self):
        """Test run_tests shows output when no results detected"""
        output = '''
U-Boot banner here
Missing required argument 'fs_image' for test 'pxe_test_sysboot'
Tests run: 1, failures: 1
'''

        def mock_run(*_args, **_kwargs):
            return command.CommandResult(return_code=1, stdout=output)

        args = cmdline.parse_args(['test', 'pxe'])
        col = terminal.Color()
        with mock.patch.object(command, 'run_one', mock_run):
            with mock.patch.object(cmdtest, 'ensure_dm_init_files',
                                   return_value=True):
                with terminal.capture() as (out, err):
                    result = cmdtest.run_tests('/path/to/sandbox',
                                               [('pxe', None)], args, col)
        self.assertEqual(1, result)
        self.assertIn('No results detected', err.getvalue())
        # Error message should be shown in output
        self.assertIn('Missing required argument', out.getvalue())

    def test_do_test_runs_tests(self):
        """Test do_test runs tests when no list flags"""
        cap = []

        def mock_run(*cmd_args, **_kwargs):
            cap.append(cmd_args)
            return command.CommandResult(return_code=0,
                                         stdout='Result: PASS dm_test\n')

        args = cmdline.parse_args(['test', 'dm'])
        args.col = terminal.Color()
        with mock.patch.object(cmdtest, 'get_sandbox_path',
                               return_value='/path/to/sandbox'):
            with mock.patch.object(cmdtest, 'validate_specs', return_value=[]):
                with mock.patch.object(cmdtest, 'ensure_dm_init_files',
                                       return_value=True):
                    with mock.patch.object(command, 'run_one', mock_run):
                        with terminal.capture():
                            result = cmdtest.do_test(args)
        self.assertEqual(0, result)
        self.assertEqual(('/path/to/sandbox', '-T', '-F', '-c', 'ut -E dm'), cap[0])

    def test_parse_one_test_suite(self):
        """Test parse_one_test with suite name"""
        self.assertEqual(('dm', None), cmdtest.parse_one_test('dm'))

    def test_parse_one_test_suite_dot_test(self):
        """Test parse_one_test with suite.test format"""
        self.assertEqual(('dm', 'test_acpi'),
                         cmdtest.parse_one_test('dm.test_acpi'))

    def test_parse_one_test_full_name(self):
        """Test parse_one_test with full test name (suite_test_name)"""
        self.assertEqual(('dm', 'acpi'), cmdtest.parse_one_test('dm_test_acpi'))

    def test_parse_one_test_test_prefix(self):
        """Test parse_one_test with test_ prefix"""
        self.assertEqual((None, 'something'),
                         cmdtest.parse_one_test('test_something'))

    def test_parse_one_test_pytest_name(self):
        """Test parse_one_test with pytest-style ut_ prefix"""
        self.assertEqual(('bootstd', 'bootflow_cmd_menu'),
                         cmdtest.parse_one_test('ut_bootstd_bootflow_cmd_menu'))

    def test_parse_test_specs_empty(self):
        """Test parse_test_specs with no tests"""
        self.assertEqual([('all', None)], cmdtest.parse_test_specs([]))

    def test_parse_test_specs_all(self):
        """Test parse_test_specs with 'all'"""
        self.assertEqual([('all', None)], cmdtest.parse_test_specs(['all']))

    def test_parse_test_specs_single(self):
        """Test parse_test_specs with single suite"""
        self.assertEqual([('dm', None)], cmdtest.parse_test_specs(['dm']))

    def test_parse_test_specs_pattern(self):
        """Test parse_test_specs with suite and glob pattern"""
        self.assertEqual([('dm', 'video*')],
                         cmdtest.parse_test_specs(['dm', 'video*']))

    def test_parse_test_specs_multiple(self):
        """Test parse_test_specs with multiple suites"""
        self.assertEqual([('dm', None), ('env', None)],
                         cmdtest.parse_test_specs(['dm', 'env']))

    def test_resolve_specs_with_suite(self):
        """Test resolve_specs passes through specs with suite"""
        specs = [('dm', None), ('env', 'basic')]
        resolved, unmatched = cmdtest.resolve_specs('/path/to/sandbox', specs)
        self.assertEqual(specs, resolved)
        self.assertEqual([], unmatched)

    def test_resolve_specs_finds_suite(self):
        """Test resolve_specs finds suite for pattern-only spec"""
        all_tests = [('dm', 'test_acpi'), ('dm', 'test_gpio'),
                     ('env', 'test_env_basic')]

        with mock.patch.object(cmdtest, 'get_tests_from_nm',
                               return_value=all_tests):
            resolved, unmatched = cmdtest.resolve_specs(
                '/path/to/sandbox', [(None, 'acpi')])

        self.assertEqual([('dm', 'acpi')], resolved)
        self.assertEqual([], unmatched)

    def test_resolve_specs_unmatched(self):
        """Test resolve_specs returns unmatched for unknown pattern"""
        all_tests = [('dm', 'test_acpi')]

        with mock.patch.object(cmdtest, 'get_tests_from_nm',
                               return_value=all_tests):
            resolved, unmatched = cmdtest.resolve_specs(
                '/path/to/sandbox', [(None, 'nonexistent')])

        self.assertEqual([], resolved)
        self.assertEqual([(None, 'nonexistent')], unmatched)

    def test_validate_specs_all(self):
        """Test validate_specs accepts 'all' without checking"""
        result = cmdtest.validate_specs('/path/to/sandbox', [('all', None)])
        self.assertEqual([], result)

    def test_validate_specs_valid_suite(self):
        """Test validate_specs accepts valid suite"""
        all_tests = [('dm', 'test_acpi'), ('dm', 'test_gpio')]

        with mock.patch.object(cmdtest, 'get_tests_from_nm',
                               return_value=all_tests):
            result = cmdtest.validate_specs('/path/to/sandbox',
                                            [('dm', None)])

        self.assertEqual([], result)

    def test_validate_specs_valid_pattern(self):
        """Test validate_specs accepts valid suite with pattern"""
        all_tests = [('dm', 'test_acpi'), ('dm', 'test_gpio')]

        with mock.patch.object(cmdtest, 'get_tests_from_nm',
                               return_value=all_tests):
            result = cmdtest.validate_specs('/path/to/sandbox',
                                            [('dm', 'acpi')])

        self.assertEqual([], result)

    def test_validate_specs_invalid_suite(self):
        """Test validate_specs returns unmatched for invalid suite"""
        all_tests = [('dm', 'test_acpi')]

        with mock.patch.object(cmdtest, 'get_tests_from_nm',
                               return_value=all_tests):
            result = cmdtest.validate_specs('/path/to/sandbox',
                                            [('nonexistent', None)])

        self.assertEqual([('nonexistent', None)], result)

    def test_validate_specs_invalid_pattern(self):
        """Test validate_specs returns unmatched for invalid pattern"""
        all_tests = [('dm', 'test_acpi')]

        with mock.patch.object(cmdtest, 'get_tests_from_nm',
                               return_value=all_tests):
            result = cmdtest.validate_specs('/path/to/sandbox',
                                            [('dm', 'nonexistent')])

        self.assertEqual([('dm', 'nonexistent')], result)

    def test_get_section_info(self):
        """Test parsing readelf output for section info"""
        readelf_output = '''
Section Headers:
  [Nr] Name              Type             Address           Offset
       Size              EntSize          Flags  Link  Info  Align
  [ 0]                   NULL             0000000000000000  00000000
       0000000000000000  0000000000000000           0     0     0
  [21] .data.rel.ro      PROGBITS         0000000001234000  00034000
       0000000000010000  0000000000000000  WA       0     0     32
'''
        result = mock.MagicMock(stdout=readelf_output)
        with mock.patch.object(command, 'run_one', return_value=result):
            addr, offset = cmdtest.get_section_info('/path/to/sandbox')
        self.assertEqual(0x01234000, addr)
        self.assertEqual(0x00034000, offset)

    def test_get_section_info_not_found(self):
        """Test get_section_info when section is missing"""
        result = mock.MagicMock(stdout='No .data.rel.ro section')
        with mock.patch.object(command, 'run_one', return_value=result):
            addr, offset = cmdtest.get_section_info('/path/to/sandbox')
        self.assertIsNone(addr)
        self.assertIsNone(offset)

    def test_predict_test_count_live_tree(self):
        """Test predict_test_count for live tree (default)"""
        flags_data = [
            ('test_a', 0),                      # No flags - runs once
            ('test_b', cmdtest.UTF_DM),         # Runs once (no flat)
            ('test_c', cmdtest.UTF_FLAT_TREE),  # Skipped on live tree
        ]
        patcher = mock.patch.object(cmdtest, 'get_test_flags',
                                    return_value=flags_data)
        with patcher:
            count = cmdtest.predict_test_count('/path/to/sandbox', 'dm')
        self.assertEqual(2, count)

    def test_predict_test_count_full(self):
        """Test predict_test_count with full=True (both tree types)"""
        flags_data = [
            ('test_a', 0),                      # No flags - runs once
            ('test_b', cmdtest.UTF_DM),         # Runs twice
            ('test_c', cmdtest.UTF_FLAT_TREE),  # Runs once (flat only)
            ('test_d', cmdtest.UTF_LIVE_TREE),  # Runs once
            ('video_test', cmdtest.UTF_DM),     # Runs once (skip flat)
        ]
        patcher = mock.patch.object(cmdtest, 'get_test_flags',
                                    return_value=flags_data)
        with patcher:
            count = cmdtest.predict_test_count('/path/to/sandbox', 'dm',
                                               full=True)
        # test_a(1) + test_b(2) + test_c(1) + test_d(1) + video(1) = 6
        self.assertEqual(6, count)

    def test_needs_dm_init_dm_suite(self):
        """Test needs_dm_init returns True for dm suite"""
        self.assertTrue(cmdtest.needs_dm_init([('dm', None)]))

    def test_needs_dm_init_all_suite(self):
        """Test needs_dm_init returns True for all tests"""
        self.assertTrue(cmdtest.needs_dm_init([('all', None)]))

    def test_needs_dm_init_other_suite(self):
        """Test needs_dm_init returns False for non-dm suite"""
        self.assertFalse(cmdtest.needs_dm_init([('env', None)]))

    def test_needs_dm_init_host_test(self):
        """Test needs_dm_init returns True for host tests"""
        self.assertTrue(cmdtest.needs_dm_init([('cmd', 'cmd_host')]))

    def test_ensure_dm_init_files_exists(self):
        """Test ensure_dm_init_files returns True if files exist"""
        with mock.patch.object(os.path, 'exists', return_value=True):
            result = cmdtest.ensure_dm_init_files()
        self.assertTrue(result)

    def test_ensure_dm_init_files_pytest_fails(self):
        """Test ensure_dm_init_files fails if run_pytest fails"""
        with mock.patch.object(os.path, 'exists', return_value=False):
            with mock.patch.object(cmdtest, 'run_pytest', return_value=False):
                with terminal.capture():
                    result = cmdtest.ensure_dm_init_files()
        self.assertFalse(result)


class TestPytestCTest(TestBase):
    """Tests for the pytest -C (C test) functionality"""

    def setUp(self):
        tout.init(tout.WARNING)
        self.test_dir = tempfile.mkdtemp()
        self.orig_config = settings.SETTINGS['config']
        settings.SETTINGS['config'] = None

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        settings.SETTINGS['config'] = self.orig_config
        super().tearDown()

    def test_find_test(self):
        """Test finding Python test file from spec"""
        # Create a mock U-Boot tree with test file
        test_fs_dir = os.path.join(self.test_dir, 'test/py/tests/test_fs')
        os.makedirs(test_fs_dir)
        test_file = os.path.join(test_fs_dir, 'test_ext4l.py')
        tools.write_file(test_file, b'# test file')

        # Test with class:method format
        path, cls, method = cmdpy.find_test(self.test_dir,
                                            'TestExt4l:test_unlink')
        self.assertEqual(test_file, path)
        self.assertEqual('TestExt4l', cls)
        self.assertEqual('test_unlink', method)

        # Test with just class name
        path, cls, method = cmdpy.find_test(self.test_dir, 'ext4l')
        self.assertEqual(test_file, path)
        self.assertIsNone(method)

        # Test not found
        path, cls, method = cmdpy.find_test(self.test_dir,
                                            'NonExistent:test_foo')
        self.assertIsNone(path)
        self.assertIsNone(cls)
        self.assertIsNone(method)

    def test_get_fixture_path(self):
        """Test extracting fixture path from a test file"""
        test_content = b'''
@pytest.fixture
def ext4_image(self, u_boot_config):
    image_path = os.path.join(u_boot_config.persistent_data_dir,
                              'ext4l_test.img')
    yield image_path
'''
        test_file = os.path.join(self.test_dir, 'test_ext4l.py')
        tools.write_file(test_file, test_content)

        with mock.patch.object(settings, 'get', return_value='/tmp/b'):
            path = cmdpy.get_fixture_path(test_file)
        self.assertEqual('/tmp/b/sandbox/persistent-data/ext4l_test.img', path)

    def test_find_run_ut_call(self):
        """Test finding run_ut() call in method AST"""
        source = '''
class TestFoo:
    def test_with_ut(self, ubman):
        ubman.run_ut('dm', 'dm_test_foo')

    def test_without_ut(self):
        pass
'''
        tree = ast.parse(source)
        cls = tree.body[0]

        # Method with run_ut() call
        method = cls.body[0]
        call = cmdpy.find_run_ut_call(method)
        self.assertIsNotNone(call)
        self.assertEqual('run_ut', call.func.attr)

        # Method without run_ut() call
        method = cls.body[1]
        call = cmdpy.find_run_ut_call(method)
        self.assertIsNone(call)

    def test_parse_c_test_call(self):
        """Test parsing a C test-command from a real test file"""
        uboot_dir = cmdpy.get_uboot_dir()
        if not uboot_dir:
            self.skipTest('Not in a U-Boot tree')

        test_file = os.path.join(uboot_dir,
                                 'test/py/tests/test_fs/test_ext4l.py')
        source = tools.read_file(test_file, binary=False)

        result = cmdpy.parse_c_test_call(source, 'TestExt4l', 'test_probe')
        self.assertIsNotNone(result[0])
        suite, c_test, arg_key, fixture = result
        self.assertEqual('fs', suite)
        self.assertEqual('fs_test_ext4l_probe_norun', c_test)
        self.assertEqual('fs_image', arg_key)
        self.assertEqual('ext4_image', fixture)

    def test_c_test_flag_parsing(self):
        """Test -C flag is parsed correctly"""
        args = cmdline.parse_args(['pytest', '-C', 'TestExt4l:test_unlink'])
        self.assertTrue(args.c_test)
        self.assertEqual(['TestExt4l:test_unlink'], args.test_spec)

    @mock.patch.object(cmdpy, 'get_uboot_dir')
    def test_run_c_test_no_spec(self, mock_uboot_dir):
        """Test run_c_test fails without test spec"""
        mock_uboot_dir.return_value = self.test_dir
        args = argparse.Namespace(test_spec=None, dry_run=False,
                                  show_cmd=False)
        with terminal.capture() as (_out, err):
            ret = cmdpy.run_c_test(args)
        self.assertEqual(1, ret)
        self.assertIn('Test spec required', err.getvalue())

    @mock.patch.object(cmdpy, 'get_uboot_dir')
    def test_run_c_test_method_required(self, mock_uboot_dir):
        """Test run_c_test fails without method name"""
        mock_uboot_dir.return_value = self.test_dir

        # Create test file without method
        test_fs_dir = os.path.join(self.test_dir, 'test/py/tests/test_fs')
        os.makedirs(test_fs_dir)
        test_file = os.path.join(test_fs_dir, 'test_ext4l.py')
        tools.write_file(test_file, b'# test')

        args = argparse.Namespace(test_spec=['ext4l'], dry_run=False,
                                  show_cmd=False)
        with terminal.capture() as (_out, err):
            ret = cmdpy.run_c_test(args)
        self.assertEqual(1, ret)
        self.assertIn('Method name required', err.getvalue())


class TestPytestPollute(TestBase):
    """Tests for the pytest --pollute functionality"""

    def setUp(self):
        tout.init(tout.WARNING)
        self.test_dir = None

    def test_pollute_flag_parsing(self):
        """Test --pollute flag is parsed correctly"""
        args = cmdline.parse_args(['pytest', '-B', 'sandbox',
                                   '--pollute', 'test_foo'])
        self.assertEqual('test_foo', args.pollute)
        self.assertEqual('sandbox', args.board)

    def test_collect_tests_parsing(self):
        """Test parsing of --collect-only output"""
        collect_output = '''test_ut.py::TestUt::test_dm
test_ut.py::TestUt::test_env
test_fs.py::TestFs::test_ext4
<Module test_other.py>
'''
        with mock.patch.object(command, 'run_pipe') as mock_run:
            mock_run.return_value = mock.Mock(
                return_code=0,
                stdout=collect_output,
                stderr='')
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      test_spec=None, build=False, full=False)
            tests = cmdpy.collect_tests(args)

        self.assertEqual(3, len(tests))
        self.assertEqual('test_ut.py::TestUt::test_dm', tests[0])
        self.assertEqual('test_ut.py::TestUt::test_env', tests[1])
        self.assertEqual('test_fs.py::TestFs::test_ext4', tests[2])

    def test_pollute_run_uses_k_with_names(self):
        """Test pollute_run uses -k with extracted test names"""
        captured_cmd = []

        def mock_popen(cmd, **_kwargs):
            captured_cmd.extend(cmd)
            proc = mock.Mock()
            proc.stdout.read.return_value = b''
            proc.returncode = 0
            return proc

        with mock.patch('subprocess.Popen', mock_popen):
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      lto=False, full=False)
            env = {}
            tests = ['tests/test_ut.py::test_ut[ut_dm_foo]',
                     'tests/test_ut.py::test_ut[ut_dm_bar]']
            target = 'tests/test_ut.py::test_ut[ut_dm_target]'
            cmdpy.pollute_run(tests, target, args, env)

        # Uses -k with extracted test names
        self.assertIn('-k', captured_cmd)
        idx = captured_cmd.index('-k')
        spec = captured_cmd[idx + 1]
        self.assertEqual('ut_dm_foo or ut_dm_bar or ut_dm_target', spec)

    def test_node_to_name(self):
        """Test node_to_name extracts test name from node ID"""
        # Parameterized test
        self.assertEqual('ut_dm_foo',
            cmdpy.node_to_name('tests/test_ut.py::test_ut[ut_dm_foo]'))
        # Non-parameterized test
        self.assertEqual('test_bar',
            cmdpy.node_to_name('tests/test_foo.py::TestClass::test_bar'))
        # Simple name
        self.assertEqual('test_simple', cmdpy.node_to_name('test_simple'))

    def test_pollute_run_uses_pollute_build_dir(self):
        """Test pollute_run uses -pollute suffix for build dir"""
        captured_cmd = []

        def mock_popen(cmd, **_kwargs):
            captured_cmd.extend(cmd)
            proc = mock.Mock()
            proc.stdout.read.return_value = b''
            proc.returncode = 0
            return proc

        with mock.patch('subprocess.Popen', mock_popen):
            with mock.patch.object(settings, 'get', return_value='/tmp/b'):
                args = argparse.Namespace(board='sandbox', build_dir=None,
                                          lto=False, full=False)
                cmdpy.pollute_run([], 'test_target', args, {})

        self.assertIn('--build-dir', captured_cmd)
        idx = captured_cmd.index('--build-dir')
        self.assertEqual('/tmp/b/sandbox-pollute', captured_cmd[idx + 1])

    def test_collect_tests_no_full_flag(self):
        """Test collect_tests adds --no-full when full=False"""
        with mock.patch.object(command, 'run_pipe') as mock_run:
            mock_run.return_value = mock.Mock(
                return_code=0, stdout='', stderr='')
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      test_spec=None, build=False, full=False)
            cmdpy.collect_tests(args)

        cmd = mock_run.call_args[0][0][0]
        self.assertIn('--no-full', cmd)

    def test_collect_tests_full_flag(self):
        """Test collect_tests omits --no-full when full=True"""
        with mock.patch.object(command, 'run_pipe') as mock_run:
            mock_run.return_value = mock.Mock(
                return_code=0, stdout='', stderr='')
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      test_spec=None, build=False, full=True)
            cmdpy.collect_tests(args)

        cmd = mock_run.call_args[0][0][0]
        self.assertNotIn('--no-full', cmd)

    def test_collect_tests_no_full_unsupported(self):
        """Test collect_tests detects --no-full not supported"""
        with mock.patch.object(command, 'run_pipe') as mock_run:
            mock_run.return_value = mock.Mock(
                return_code=4, stdout='',
                stderr='error: unrecognized arguments: --no-full')
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      test_spec=None, build=False, full=False)
            with terminal.capture() as (_, err):
                result = cmdpy.collect_tests(args)

        self.assertIsNone(result)
        self.assertIn('--no-full', err.getvalue())
        self.assertIn('use -f', err.getvalue())

    def test_pollute_run_no_full_flag(self):
        """Test pollute_run adds --no-full when full=False"""
        captured_cmd = []

        def mock_popen(cmd, **_kwargs):
            captured_cmd.extend(cmd)
            proc = mock.Mock()
            proc.stdout.read.return_value = b''
            proc.returncode = 0
            return proc

        with mock.patch('subprocess.Popen', mock_popen):
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      lto=False, full=False)
            cmdpy.pollute_run([], 'test_target', args, {})

        self.assertIn('--no-full', captured_cmd)

    def test_pollute_run_full_flag(self):
        """Test pollute_run omits --no-full when full=True"""
        captured_cmd = []

        def mock_popen(cmd, **_kwargs):
            captured_cmd.extend(cmd)
            proc = mock.Mock()
            proc.stdout.read.return_value = b''
            proc.returncode = 0
            return proc

        with mock.patch('subprocess.Popen', mock_popen):
            args = argparse.Namespace(board='sandbox', build_dir=None,
                                      lto=False, full=True)
            cmdpy.pollute_run([], 'test_target', args, {})

        self.assertNotIn('--no-full', captured_cmd)

    def test_pollute_build_to_pollute_dir(self):
        """Test --pollute -b builds to pollute directory"""
        cap = []

        def mock_exec_cmd(cmd, *args, **kwargs):
            cap.append(cmd)
            return command.CommandResult(return_code=0)

        def mock_collect(**_kwargs):
            return command.CommandResult(
                stdout='test_ut.py::TestUt::test_dm_foo\n'
                       'test_ut.py::TestUt::test_dm_bar\n',
                return_code=0)

        command.TEST_RESULT = mock_collect

        args = make_args(cmd='pytest', board='sandbox', build=True,
                         pollute='test_dm_foo')
        with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
            with mock.patch.object(cmdpy, 'exec_cmd', mock_exec_cmd):
                with terminal.capture():
                    control.run_command(args)

        # First command should be buildman to pollute directory
        self.assertIn('buildman', cap[0])
        self.assertIn('-o', cap[0])
        idx = cap[0].index('-o')
        self.assertIn('-pollute', cap[0][idx + 1])

    def test_pollute_build_respects_lto(self):
        """Test --pollute -b -L respects LTO flag"""
        cap = []

        def mock_exec_cmd(cmd, *args, **kwargs):
            cap.append(cmd)
            return command.CommandResult(return_code=0)

        def mock_collect(**_kwargs):
            return command.CommandResult(
                stdout='test_ut.py::TestUt::test_dm_foo\n',
                return_code=0)

        command.TEST_RESULT = mock_collect

        # With lto=True, -L should NOT be in buildman command
        args = make_args(cmd='pytest', board='sandbox', build=True,
                         lto=True, pollute='test_dm_foo')
        with mock.patch.object(build, 'setup_uboot_dir', return_value=True):
            with mock.patch.object(cmdpy, 'exec_cmd', mock_exec_cmd):
                with terminal.capture():
                    control.run_command(args)

        self.assertNotIn('-L', cap[0])
