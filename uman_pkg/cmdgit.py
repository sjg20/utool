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


def get_upstream():
    """Get the upstream branch name

    Returns:
        str: Upstream branch name, or None if not found
    """
    # Try @{upstream} first
    try:
        upstream = git_output('name-rev', '@{upstream}', '--name-only')
        if upstream:
            return upstream
    except command.CommandExc:
        pass

    # Maybe we are in a rebase - try @{-1}
    try:
        upstream = git_output('name-rev', '@{-1}', '--name-only')
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


def do_rb(args):
    """Start interactive rebase to upstream

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

    return git('rebase', '-i', target)


def do_rf(args):
    """Start interactive rebase with first commit set to edit

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

    # Set GIT_SEQUENCE_EDITOR to change first line to 'edit'
    env = os.environ.copy()
    env['GIT_SEQUENCE_EDITOR'] = "sed -i '1s/^pick/edit/'"

    return git('rebase', '-i', target, env=env)


def do_rp(args):
    """Rebase to upstream, stop at patch N for editing

    Args:
        args (argparse.Namespace): Arguments from cmdline
            args.arg: Patch number to stop at (required)

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    if not args.arg:
        tout.error('Patch number required: um git rp N')
        return 1

    target = get_upstream()
    if not target:
        tout.error('Cannot determine upstream branch')
        return 1

    # Set GIT_SEQUENCE_EDITOR to change line N to 'edit'
    env = os.environ.copy()
    env['GIT_SEQUENCE_EDITOR'] = f"sed -i '{args.arg}s/^pick/edit/'"

    return git('rebase', '-i', target, env=env)


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

    todo_file = os.path.join(rebase_dir, 'git-rebase-todo')
    if not os.path.exists(todo_file):
        tout.error('Rebase todo file not found')
        return 1

    # If there are staged changes, we just resolved a conflict - insert break
    # so we stop at this commit after it's applied
    if has_staged_changes():
        tout.notice('Continuing after conflict resolution...')
        with open(todo_file, 'r', encoding='utf-8') as inf:
            lines = inf.readlines()
        # Insert break at the beginning of todo
        lines.insert(0, 'break\n')
        with open(todo_file, 'w', encoding='utf-8') as outf:
            outf.writelines(lines)
        return git('rebase', '--continue')

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

    if not non_comment_indices:
        tout.notice('No more steps in todo list. Continuing...')
    else:
        # Change the last one to 'edit'
        target_idx = non_comment_indices[-1]
        original = lines[target_idx].strip()
        tout.info(f'Found step {skip_count}: {original}')
        tout.notice(f'Changing step {skip_count} to edit and continuing...')
        lines[target_idx] = re.sub(r'^\S+', 'edit', lines[target_idx])

        with open(todo_file, 'w', encoding='utf-8') as outf:
            outf.writelines(lines)

    return git('rebase', '--continue')


def do_rc(args):
    """Continue the current rebase

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    del args  # unused
    return git('rebase', '--continue')


def do_rs(args):
    """Skip the current commit in rebase

    Args:
        args (argparse.Namespace): Arguments from cmdline (unused)

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    del args  # unused
    return git('rebase', '--skip')


ACTIONS = {
    'rb': do_rb,
    'rf': do_rf,
    'rp': do_rp,
    'rn': do_rn,
    'rc': do_rc,
    'rs': do_rs,
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
        return func(args)

    tout.error(f'Unknown action: {args.action}')
    return 1
