# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Handles the main control logic of st tool

This module provides various functions called by the main program to implement
the features of st.
"""

import configparser
import os
import sys

# Import patman modules
sys.path.append('/home/sglass/u/tools')
from patman import patchstream  # pylint: disable=import-error,wrong-import-position
from u_boot_pylib import command  # pylint: disable=import-error,wrong-import-position
from u_boot_pylib import gitutil  # pylint: disable=import-error,wrong-import-position
from u_boot_pylib import tout  # pylint: disable=import-error,wrong-import-position
from pickman import gitlab_api  # pylint: disable=import-error,wrong-import-position

from utool_pkg.gitlab_parser import GitLabCIParser  # pylint: disable=wrong-import-position

# Default config file content
DEFAULT_CONFIG = '''# utool config file

[DEFAULT]
# Build directory for U-Boot out-of-tree builds
build_dir = /tmp/b

# OPENSBI firmware path for RISC-V testing
opensbi = ~/dev/riscv/riscv64-fw_dynamic.bin

# U-Boot test hooks directory
test_hooks = /vid/software/devel/ubtest/u-boot-test-hooks
'''

# Global settings storage
SETTINGS = {'config': None}


def get_settings():
    """Get or create the global settings instance

    Returns:
        configparser.ConfigParser: Settings object
    """
    if SETTINGS['config'] is None:
        SETTINGS['config'] = configparser.ConfigParser()
        fname = os.path.expanduser('~/.utool')
        if not os.path.exists(fname):
            tout.notice(f'Creating config file: {fname}')
            with open(fname, 'w', encoding='utf-8') as fil:
                fil.write(DEFAULT_CONFIG)
        SETTINGS['config'].read(fname)
    return SETTINGS['config']


def get_setting(name, fallback=None):
    """Get a setting by name

    Args:
        name (str): Name of setting to retrieve
        fallback (str or None): Value to return if the setting is missing

    Returns:
        str: Setting value with ~ and env vars expanded
    """
    settings = get_settings()
    raw = settings.get('DEFAULT', name, fallback=fallback)
    return os.path.expandvars(os.path.expanduser(raw))


def build_ci_vars(args):
    """Build CI variables based on command line arguments

    Args:
        args (argparse.Namespace): Arguments object with CI flags

    Returns:
        dict: Dictionary of CI variables and their values
    """
    ci_vars = {
        'SUITES': '0',
        'PYTEST': '0',
        'WORLD': '0',
        'SJG_LAB': ''
    }

    if not args.null:
        ci_flags_set = (args.suites or args.pytest or args.world or
                       args.sjg or args.test_spec)

        if not ci_flags_set:
            ci_vars['SUITES'] = '1'
            ci_vars['PYTEST'] = '1'
            ci_vars['WORLD'] = '1'
        else:
            if args.suites:
                ci_vars['SUITES'] = '1'
            # Use 'is not None' for args with nargs='?' to distinguish between
            # not provided (None) and provided with default value ('1')
            if args.pytest is not None:
                ci_vars['PYTEST'] = args.pytest
            if args.world:
                ci_vars['WORLD'] = '1'
            if args.sjg is not None:
                ci_vars['SJG_LAB'] = args.sjg
            if args.test_spec:
                ci_vars['TEST_SPEC'] = args.test_spec

    return ci_vars


def build_commit_tags(args, ci_vars):  # pylint: disable=unused-argument
    """Build commit message tags based on CI variables for MR pipelines

    Args:
        args (argparse.Namespace): Arguments object with CI flags
        ci_vars (dict): CI variables dictionary

    Returns:
        str: Space-separated commit message tags
    """
    tags = []

    # Add skip tags for variables set to '0' or empty
    if ci_vars.get('SUITES') == '0':
        tags.append('[skip-suites]')
    if ci_vars.get('PYTEST') == '0':
        tags.append('[skip-pytest]')
    if ci_vars.get('WORLD') == '0':
        tags.append('[skip-world]')
    if ci_vars.get('SJG_LAB') in ('0', ''):
        tags.append('[skip-sjg]')

    return ' '.join(tags)


def append_tags_to_description(desc, tags):
    """Append commit message tags to MR description

    Args:
        desc (str): Original description (empty string if no description)
        tags (str): Space-separated tags to append

    Returns:
        str: Description with tags appended
    """
    if not tags:
        return desc

    if desc:
        return f'{desc}\n\n{tags}'
    return tags


def run_or_show_command(cmd, args):
    """Run a command or show what would be run in dry-run mode

    Args:
        cmd (list): Command to run
        args (argparse.Namespace): Arguments object containing dry_run flag

    Returns:
        CommandResult or None: Result if run, None if dry-run
    """
    if args.dry_run:
        # Only show git push commands in dry-run mode
        if cmd[0] == 'git' and cmd[1] == 'push':
            tout.notice(' '.join(cmd))
        return None

    tout.info(f"Running: {' '.join(cmd)}")
    return command.run_pipe([cmd], raise_on_error=True)


def git_push_branch(branch, args, ci_vars=None, upstream=False, dest=None):
    """Push a branch to the 'ci' remote with optional CI variables

    Args:
        branch (str): Branch name to push
        args (argparse.Namespace): Command line arguments (contains force, dry_run, dest flags)
        ci_vars (dict): Optional CI variables to include as push options
        upstream (bool): Whether to set upstream with -u flag
        dest (str): Destination branch name (defaults to args.dest or current branch name)

    Returns:
        CommandResult or None: Result of push command
    """
    push_cmd = ['git', 'push']

    if args.force:
        push_cmd.append('--force')

    if upstream:
        push_cmd.append('-u')

    if ci_vars:
        for key, value in ci_vars.items():
            push_cmd.extend(['-o', f'ci.variable={key}={value}'])

    # Determine destination branch - use provided dest, or fall back to args.dest, or current branch
    dest_branch = dest or getattr(args, 'dest', None) or branch

    # Always push to 'ci' remote, but to the specified destination branch
    if dest_branch == branch:
        # Same branch name, simple push
        push_cmd.extend(['ci', branch])
    else:
        # Different branch name, use refspec
        push_cmd.extend(['ci', f'{branch}:{dest_branch}'])

    return run_or_show_command(push_cmd, args)


def show_pytest_choices(parser):
    """Show all available pytest choices (boards + job names)

    Args:
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        int: Exit code (always 0)
    """
    tout.notice('Available pytest targets:')
    tout.notice('')
    tout.notice('Special values:')
    tout.notice('  1                    - Run all pytest jobs')
    tout.notice('')
    tout.notice('Board names (targets all jobs for that board):')
    for board in parser.boards:
        tout.notice(f'  {board}')

    tout.notice('')
    tout.notice('Job names (targets specific job variant):')
    for job in parser.job_names:
        tout.notice(f'  {job}')
    return 0


def show_sjg_choices(parser):
    """Show all available SJG_LAB choices

    Args:
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        int: Exit code (always 0)
    """
    tout.notice('Available SJG_LAB targets:')
    tout.notice('')
    tout.notice('Special values:')
    tout.notice('  1                    - Run all lab jobs')
    tout.notice('  (empty)              - Manual lab jobs only')
    tout.notice('')
    tout.notice('Lab names:')
    for role in parser.roles:
        tout.notice(f'  {role}')

    return 0


def validate_pytest_value(value, parser):
    """Validate a pytest value against available choices

    Args:
        value (str): Value to validate
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        bool: True if valid, False otherwise
    """
    if value in ('1', 'help'):
        return True
    return value in parser.boards or value in parser.job_names


def validate_sjg_value(value, parser):
    """Validate an SJG_LAB value against available choices

    Args:
        value (str): Value to validate
        parser (GitLabCIParser): GitLabCIParser instance

    Returns:
        bool: True if valid, False otherwise
    """
    if value in ('1', '', 'help'):
        return True
    return value in parser.roles


def validate_ci_args(args):
    """Validate CI arguments and handle help requests

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code (0 for success, non-zero for failure, None to continue)
    """
    # Parse GitLab CI file once for validation and help requests
    parser = GitLabCIParser()

    # Handle help requests
    if args.pytest == 'help':
        return show_pytest_choices(parser)
    if args.sjg == 'help':
        return show_sjg_choices(parser)

    # Validate pytest argument
    if args.pytest is not None:
        if not validate_pytest_value(args.pytest, parser):
            tout.error(f'Invalid pytest value: {args.pytest}')
            tout.notice(f'To see available choices: {sys.argv[0]} ci -p help')
            return 1

    # Validate sjg argument
    if args.sjg is not None:
        if not validate_sjg_value(args.sjg, parser):
            tout.error(f'Invalid SJG_LAB value: {args.sjg}')
            tout.notice(f'To see available choices: {sys.argv[0]} ci -l help')
            return 1

    # All validation passed
    return None


def run_command(args):
    """Run the appropriate command based on parsed arguments

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    # Set verbosity level
    tout.init(tout.INFO if args.verbose else tout.NOTICE)

    tout.info(f'Running command: {args.cmd}')

    if args.cmd == 'ci':
        # Validate CI arguments and handle help requests
        result = validate_ci_args(args)
        if result is not None:
            return result

        if args.merge:
            return do_merge_request(args)
        return do_ci(args)

    if args.cmd == 'pytest':
        return do_pytest(args)

    tout.error(f'Unknown command: {args.cmd}')
    return 1


def extract_mr_title_description(branch, args):
    """Extract title and description for merge request from patch series
    
    Args:
        branch (str): Current git branch name
        args (argparse.Namespace): Arguments from cmdline
        
    Returns:
        tuple: (title_str, description_str, commit_tags) or (None, None, None) if error
    """
    start = 0
    end = 0

    # Work out how many patches to send if we can
    count = gitutil.count_commits_to_branch(branch) - start
    series = patchstream.get_metadata(branch, start, count - end)

    # For single commit, use commit subject/body; for multiple commits, require cover letter
    if count - end == 1:
        # Single commit - use the commit subject as title and body as description
        commit = series.commits[0]
        title = commit.subject
        description = commit.msg if commit.msg else ''
        tout.info('Using single commit subject and body for merge request')
    else:
        # Multiple commits - require cover letter
        if not series.get('cover'):
            tout.error('No cover letter found in patch series')
            tout.notice('Use \'git format-patch --cover-letter\' or add a '
                        'cover letter to your series')
            return None, None, None
        title = series.get('cover')
        description = series.notes if series.notes else ''
        tout.info('Using cover letter for merge request')

    tout.info(f'Found {count - end} patches for branch {branch}')

    if not title:
        tout.error('Could not extract title')
        return None, None, None

    # Ensure title and description are strings
    if isinstance(title, list):
        # If title is a list, use the first non-empty line
        title_str = next((line.strip() for line in title
                           if line.strip()), '')
    else:
        title_str = str(title) if title is not None else ''

    description_str = str(description) if description is not None else ''

    # Build CI variables for pipeline creation
    ci_vars = build_ci_vars(args)
    # When creating MR, append commit message tags for pipeline control
    commit_tags = ''
    if hasattr(args, 'merge') and args.merge:
        commit_tags = build_commit_tags(args, ci_vars)
        description_str = append_tags_to_description(description_str,
                                                     commit_tags)

    return title_str, description_str, commit_tags


def do_merge_request(args):
    """Create a merge request using cover letter from patch series

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    tout.info('Creating merge request from patch series...')

    # Get branch and extract title/description
    branch = gitutil.get_branch()
    title_str, description_str, commit_tags = extract_mr_title_description(branch, args)
    if title_str is None:
        return 1

    if args.dry_run:
        tout.notice(f'dry-run: Create MR \'{title_str}\'')
        return 0

    # Push branch with CI variables - respects --null flag
    tout.info('Pushing branch...')
    ci_vars = build_ci_vars(args)
    git_push_branch(branch, args, ci_vars=ci_vars, upstream=True)

    # Get remote URL and parse it using pickman's functions
    remote_url = gitlab_api.get_remote_url('ci')
    host, proj_path = gitlab_api.parse_url(remote_url)
    if not host or not proj_path:
        tout.error(f'Cannot parse remote URL: {remote_url}')
        return 1

    tout.info('Creating merge request...')
    mr_url = gitlab_api.create_mr(host, proj_path, branch, 'master',
                                  title_str, description_str)

    if not mr_url:
        tout.error('Failed to create merge request')
        return 1

    tout.notice(f'Merge request: {mr_url}')
    if commit_tags:
        tout.info(f'MR pipeline will use commit message tags: {commit_tags}')

    return 0


def do_ci(args):
    """Handle CI command - push current branch to trigger CI

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    branch = command.output_one_line('git', 'branch', '--show-current')

    if not branch:
        tout.error('Could not determine current branch')
        return 1

    tout.info(f'Current branch: {branch}')

    ci_vars = build_ci_vars(args)

    git_push_branch(branch, args, ci_vars=ci_vars)

    return 0


def pytest_env(board):
    """Set up environment variables for pytest testing

    Args:
        board (str): Board name

    Returns:
        dict: Environment variables that were set (not the full environment)
    """
    env_vars = {}

    # Set up cross-compiler using buildman
    try:
        cross_compile = command.output_one_line('buildman', '-A', board)
        if cross_compile:
            env_vars['CROSS_COMPILE'] = cross_compile
    except command.CommandExc:
        tout.warning(f'Could not determine cross-compiler for {board}')

    if 'riscv' in board:
        opensbi = get_setting('opensbi')
        if opensbi and os.path.exists(opensbi):
            env_vars['OPENSBI'] = opensbi
        else:
            tout.warning('No OPENSBI firmware found for RISC-V')

    test_hooks_path = get_setting('test_hooks')
    if test_hooks_path and os.path.exists(test_hooks_path):
        current_path = os.environ.get('PATH', '')
        if test_hooks_path not in current_path:
            env_vars['PATH'] = f"{current_path}:{test_hooks_path}"

    return env_vars


def do_pytest(args):
    """Handle pytest command - run pytest tests for U-Boot

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    tout.info(f'Running pytest for board: {args.board}')

    env_vars = pytest_env(args.board)

    cmd = ['./test/py/test.py']
    cmd.extend(['-B', args.board])

    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = get_setting('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{args.board}'
    cmd.extend(['--build-dir', build_dir])

    if not args.no_build:
        cmd.append('--build')

    cmd.extend(['--id', 'na'])

    if args.test_spec:
        cmd.extend(['-k', ' '.join(args.test_spec)])

    if args.timeout != 300:
        cmd.extend(['-o', f'faulthandler_timeout={args.timeout}'])

    cmd.append('-q')
    if args.show_output:
        cmd.append('-s')

    if args.dry_run:
        tout.notice(f"Would run: {' '.join(cmd)}")
        if env_vars:
            tout.notice("Environment variables:")
            for key, value in env_vars.items():
                tout.notice(f"  {key}={value}")
        return 0

    tout.notice(f"+ {' '.join(cmd)}")
    for key, value in env_vars.items():
        tout.notice(f"+ export {key}={value}")

    env = os.environ.copy()
    env.update(env_vars)
    result = command.run_pipe([cmd], raise_on_error=False, env=env, capture=False)

    if result.return_code != 0:
        tout.error('pytest failed')
        return result.return_code

    tout.notice('pytest passed')
    return 0
