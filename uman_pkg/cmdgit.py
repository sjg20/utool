# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Git command for rebase helpers

This module handles the 'git' subcommand which provides interactive rebase
helpers similar to the rf/rn bash aliases.
"""

import os
import re

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from uman_pkg.util import git, git_output


def get_rebase_position():
    """Get current position in rebase (e.g., "3/12")

    Returns:
        str: Position string like "3/12", or empty string if not available
    """
    for subdir in ['rebase-merge', 'rebase-apply']:
        try:
            path = git_output('rev-parse', '--git-path', subdir)
            if os.path.isdir(path):
                msgnum_file = os.path.join(path, 'msgnum')
                end_file = os.path.join(path, 'end')
                if os.path.exists(msgnum_file) and os.path.exists(end_file):
                    with open(msgnum_file, encoding='utf-8') as inf:
                        msgnum = inf.read().strip()
                    with open(end_file, encoding='utf-8') as inf:
                        end = inf.read().strip()
                    return f'{msgnum}/{end}'
        except (command.CommandExc, OSError):
            pass
    return ''


def show_rebase_status(output, return_code=0):
    """Parse git rebase output and show a single-line status

    Args:
        output (str): Output from git rebase command (stderr or combined)
        return_code (int): Return code from git command
    """
    match = re.search(r'(Successfully rebased and updated [^.]+)', output)
    if match:
        tout.notice(match.group(1))
        return

    pos = get_rebase_position()
    pos_str = f' {pos}:' if pos else ':'

    match = re.search(r'Stopped at ([0-9a-f]+)\.\.\.\s+(.+)', output)
    if match:
        tout.notice(f'Rebasing{pos_str} stopped at {match.group(1)}... '
                    f'{match.group(2)}')
        return

    if return_code:
        match = re.search(r'Could not apply ([0-9a-f]+)\.\.\. (.+)', output)
        if match:
            tout.notice(f'Rebasing{pos_str} conflict in {match.group(1)}... '
                        f'{match.group(2)}')


def seq_edit_env(action, line=1):
    """Create environment with GIT_SEQUENCE_EDITOR set

    Args:
        action (str): 'break' to insert break, 'edit' to change pick to edit
        line (int): Line number to operate on (default 1)

    Returns:
        dict: Environment with GIT_SEQUENCE_EDITOR set
    """
    env = os.environ.copy()
    if action == 'break':
        env['GIT_SEQUENCE_EDITOR'] = f'sed -i "{line}i break"'
    else:  # edit
        env['GIT_SEQUENCE_EDITOR'] = f'sed -i "{line}s/^pick/edit/"'
    return env


def get_upstream():
    """Get the upstream branch name

    Returns:
        str: Upstream branch name, or None if not found
    """
    # Try @{upstream} first
    try:
        upstream = git_output('rev-parse', '--abbrev-ref', '@{upstream}')
        if upstream:
            return upstream
    except command.CommandExc:
        pass

    # Maybe we are in a rebase - try @{-1}
    try:
        upstream = git_output('rev-parse', '--abbrev-ref', '@{-1}')
        if upstream:
            tout.warning(f'Using upstream branch {upstream}')
            return upstream
    except command.CommandExc:
        pass

    return None


def get_rebase_dir():
    """Find the git rebase directory

    Returns:
        str: Path to rebase directory, or None if not in a rebase
    """
    try:
        path = git_output('rev-parse', '--git-path', 'rebase-merge')
        if os.path.isdir(path):
            return path
    except command.CommandExc:
        pass

    try:
        path = git_output('rev-parse', '--git-path', 'rebase-apply')
        if os.path.isdir(path):
            return path
    except command.CommandExc:
        pass

    return None


def do_gr(args):
    """Start interactive rebase to upstream, opening editor

    Args:
        args (argparse.Namespace): Arguments from cmdline
            args.arg: Number of commits back from HEAD, or None for upstream

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    if args.arg:
        target = f'HEAD~{args.arg}'
    else:
        target = get_upstream()
        if not target:
            tout.error('Cannot determine upstream branch')
            return 1

    if args.dry_run:
        tout.notice(f"git rebase -i {target}")
        return 0

    result = command.run_one('git', 'rebase', '-i', target, capture=False,
                             raise_on_error=False)
    return result.return_code


def do_rb(args):
    """Rebase from beginning - stop at upstream before first commit

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        CommandResult or int: Result with return_code, stdout, stderr; or 0
    """
    target = get_upstream()
    if not target:
        tout.error('Cannot determine upstream branch')
        return 1

    result = git('rebase', '-i', target, env=seq_edit_env('break'),
                 dry_run=args.dry_run)
    if result is None:
        return 0
    show_rebase_status(result.stdout + result.stderr, result.return_code)
    return result


def do_rf(args):
    """Start interactive rebase with first commit set to edit

    Args:
        args (argparse.Namespace): Arguments from cmdline
            args.arg: Number of commits back from HEAD, or None for upstream

    Returns:
        CommandResult or int: Result with return_code, stdout, stderr; or 0
    """
    if args.arg:
        target = f'HEAD~{args.arg}'
    else:
        target = get_upstream()
        if not target:
            tout.error('Cannot determine upstream branch')
            return 1

    result = git('rebase', '-i', target, env=seq_edit_env('edit'),
                 dry_run=args.dry_run)
    if result is None:
        return 0
    show_rebase_status(result.stdout + result.stderr, result.return_code)
    return result


def do_rp(args):
    """Rebase to upstream, stop at patch N for editing

    Args:
        args (argparse.Namespace): Arguments from cmdline
            args.arg: Patch number (0 = upstream, before first commit)

    Returns:
        CommandResult or int: Result with return_code, stdout, stderr; or 0
    """
    if args.arg is None:
        tout.error('Patch number required: um git rp N')
        return 1

    target = get_upstream()
    if not target:
        tout.error('Cannot determine upstream branch')
        return 1

    if args.arg == 0:
        env = seq_edit_env('break')
    else:
        env = seq_edit_env('edit', args.arg)

    result = git('rebase', '-i', target, env=env, dry_run=args.dry_run)
    if result is None:
        return 0
    show_rebase_status(result.stdout + result.stderr, result.return_code)
    return result


def has_conflicts():
    """Check if there are unresolved conflicts

    Returns:
        bool: True if there are conflicts (UU or AA in git status)
    """
    try:
        status = git_output('status', '--porcelain')
        for line in status.splitlines():
            if line.startswith('UU ') or line.startswith('AA '):
                return True
    except command.CommandExc:
        pass
    return False


def has_staged_changes():
    """Check if there are staged changes (index differs from HEAD)

    Returns:
        bool: True if there are staged changes
    """
    try:
        # --cached compares index to HEAD; exit code 1 means differences
        git_output('diff', '--cached', '--quiet')
        return False
    except command.CommandExc:
        return True


def has_unstaged_changes():
    """Check if there are unstaged changes (working tree differs from index)

    Returns:
        bool: True if there are unstaged changes
    """
    try:
        # Without --cached, compares working tree to index
        git_output('diff', '--quiet')
        return False
    except command.CommandExc:
        return True


def do_rn(args):
    """Continue rebase, setting next commit(s) to edit

    If there are unresolved conflicts, reports an error.
    If there are staged changes (just resolved a conflict), just continues.
    If stopped at an edit point, sets the next commit to edit and continues.

    Args:
        args (argparse.Namespace): Arguments from cmdline
            args.arg: Number of commits to skip (default 1)

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    rebase_dir = get_rebase_dir()
    if not rebase_dir:
        tout.error('Not in the middle of a git rebase')
        return 1

    # If there are conflicts, user must resolve them first
    if has_conflicts():
        tout.error('Resolve conflicts first, then use rn')
        return 1

    # If there are unstaged changes (but no staged), warn user
    if has_unstaged_changes() and not has_staged_changes():
        tout.error('Unstaged changes - use "git add" or "git checkout" first')
        return 1

    todo_file = os.path.join(rebase_dir, 'git-rebase-todo')
    if not os.path.exists(todo_file):
        tout.error('Rebase todo file not found')
        return 1

    # If there are staged changes, we just resolved a conflict - insert break
    # so we stop at this commit after it's applied
    if has_staged_changes():
        with open(todo_file, 'r', encoding='utf-8') as inf:
            lines = inf.readlines()
        # Insert break at the beginning of todo
        lines.insert(0, 'break\n')
        with open(todo_file, 'w', encoding='utf-8') as outf:
            outf.writelines(lines)
        result = git('rebase', '--continue')
        show_rebase_status(result.stdout + result.stderr, result.return_code)
        return result

    with open(todo_file, 'r', encoding='utf-8') as inf:
        lines = inf.readlines()

    # Find non-comment lines
    skip_count = args.arg or 1
    non_comment_indices = []
    for i, line in enumerate(lines):
        if line.strip() and not line.startswith('#'):
            non_comment_indices.append(i)
            if len(non_comment_indices) >= skip_count:
                break

    if non_comment_indices:
        # Change the last one to 'edit'
        target_idx = non_comment_indices[-1]
        lines[target_idx] = re.sub(r'^\S+', 'edit', lines[target_idx])

        with open(todo_file, 'w', encoding='utf-8') as outf:
            outf.writelines(lines)

    result = git('rebase', '--continue')
    show_rebase_status(result.stdout + result.stderr, result.return_code)
    return result

def do_rc(args):
    """Continue the current rebase

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int or CommandResult: 1 if not rebasing, else CommandResult
    """
    del args  # unused
    if not get_rebase_dir():
        tout.error('Not in the middle of a rebase')
        return 1
    result = git('rebase', '--continue')
    show_rebase_status(result.stdout + result.stderr, result.return_code)
    return result

def do_rs(args):
    """Skip the current commit in rebase

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int or CommandResult: 1 if not rebasing, else CommandResult
    """
    del args  # unused
    if not get_rebase_dir():
        tout.error('Not in the middle of a rebase')
        return 1
    result = git('rebase', '--skip')
    if result.return_code == 0:
        show_rebase_status(result.stdout + result.stderr)
    return result


def do_re(args):
    """Amend the current commit during rebase (rebase edit)

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int: Exit code from git commit --amend
    """
    del args  # unused
    if not get_rebase_dir():
        tout.error('Not in the middle of a rebase')
        return 1

    # Check if there are staged changes to amend
    if not has_staged_changes():
        tout.error('No staged changes to amend')
        return 1

    result = command.run_one('git', 'commit', '--amend', '--no-edit',
                             capture=True, raise_on_error=False)
    if result.return_code == 0:
        tout.notice('Commit amended')
    else:
        tout.error(result.stderr.strip() if result.stderr else 'Amend failed')
    return result.return_code


def do_ra(args):
    """Abort the current rebase

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int or CommandResult: 1 if not rebasing, else CommandResult
    """
    del args  # unused
    if not get_rebase_dir():
        tout.error('Not in the middle of a rebase')
        return 1

    # Get HEAD first for stash message and recovery info
    head = None
    try:
        head = git_output('rev-parse', '--short', 'HEAD')
    except command.CommandExc:
        pass

    # Stash uncommitted changes before aborting
    try:
        status = git_output('status', '--porcelain')
        if status:
            msg = f'uman-abort-{head}' if head else 'uman-abort'
            stash_result = git('stash', 'push', '-m', msg)
            if stash_result.return_code == 0:
                tout.notice(f'Stashed as "{msg}" (use "git stash pop" '
                            'to recover)')
            else:
                tout.warning('Could not stash changes - they may be lost')
        else:
            tout.notice('No uncommitted changes')
    except command.CommandExc:
        pass

    # Print current HEAD so user can recover if needed
    if head:
        tout.notice(f'Current HEAD: {head} (use "git reset --hard {head}" '
                    'to recover)')
    result = git('rebase', '--abort')
    if result.return_code == 0:
        tout.notice('Rebase aborted')
    return result


def do_et(args):
    """Edit the rebase todo list

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int: Exit code from git rebase --edit-todo
    """
    del args  # unused
    if not get_rebase_dir():
        tout.error('Not in the middle of a rebase')
        return 1

    result = command.run_one('git', 'rebase', '--edit-todo', capture=False,
                             raise_on_error=False)
    return result.return_code


def do_us(args):
    """Set upstream branch for current branch

    Args:
        args (argparse.Namespace): Arguments from cmdline
            args.arg: Not used (upstream passed separately)

    Returns:
        int: Exit code (0 for success)
    """
    del args  # unused for now - could add upstream argument later
    try:
        branch = git_output('rev-parse', '--abbrev-ref', 'HEAD')
    except command.CommandExc:
        tout.error('Cannot determine current branch')
        return 1

    # Default upstream is m/master
    upstream = 'm/master'

    result = git('branch', '--set-upstream-to', upstream, branch)
    if result.return_code == 0:
        tout.notice(f'Set upstream of {branch} to {upstream}')
    else:
        tout.error(result.stderr.strip() if result.stderr else
                   'Failed to set upstream')
    return result.return_code


def do_pm(args):
    """Apply patch from rebase-apply directory

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int: Exit code from patch command
    """
    del args  # unused
    rebase_dir = get_rebase_dir()
    if not rebase_dir:
        tout.error('Not in the middle of a rebase')
        return 1

    patch_file = os.path.join(rebase_dir, 'patch')
    if not os.path.exists(patch_file):
        tout.error('No patch file found in rebase directory')
        return 1

    with open(patch_file, 'r', encoding='utf-8') as patch_f:
        result = command.run_one('patch', '-p1', '--merge', capture=False,
                                 raise_on_error=False, stdin=patch_f)
    return result.return_code


ACTIONS = {
    'et': do_et,
    'gr': do_gr,
    'pm': do_pm,
    'ra': do_ra,
    'rb': do_rb,
    're': do_re,
    'rf': do_rf,
    'rp': do_rp,
    'rn': do_rn,
    'rc': do_rc,
    'rs': do_rs,
    'us': do_us,
}


def run(args):
    """Handle git subcommand

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    func = ACTIONS.get(args.action)
    if func:
        result = func(args)
        # Functions may return int or CommandResult
        if hasattr(result, 'return_code'):
            return result.return_code
        return result

    tout.error(f'Unknown action: {args.action}')
    return 1
