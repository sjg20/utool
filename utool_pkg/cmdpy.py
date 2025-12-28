# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Pytest command for running U-Boot tests

This module handles the 'pytest' subcommand which runs U-Boot's pytest
test framework.
"""

import ast
import os
import re
import socket

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from utool_pkg import settings
from utool_pkg.util import exec_cmd, get_uboot_dir, setup_uboot_dir


def setup_riscv_env(board, env):
    """Set up OPENSBI environment for RISC-V boards

    Args:
        board (str): Board name
        env (dict): Environment variables dict to update
    """
    # Select 32-bit or 64-bit OpenSBI based on board name
    if 'riscv32' in board:
        opensbi = settings.get('opensbi_rv32', fallback=None)
        # Fallback: derive rv32 path from rv64 path
        if not opensbi:
            rv64_path = settings.get('opensbi', fallback=None)
            if rv64_path:
                opensbi = rv64_path.replace('.bin', '_rv32.bin')
    else:
        opensbi = settings.get('opensbi', fallback=None)
    if opensbi and os.path.exists(opensbi):
        env['OPENSBI'] = opensbi
    elif opensbi:
        tout.warning(f'OPENSBI firmware not found: {opensbi}')
    else:
        tout.warning(f'No OPENSBI firmware configured for {board}')


def setup_sbsa_env(board, env):
    """Set up TF-A environment for SBSA boards

    Args:
        board (str): Board name
        env (dict): Environment variables dict to update
    """
    tfa_dir = settings.get('tfa_dir', fallback=None)
    # Fallback: derive tfa_dir from blobs_dir
    if not tfa_dir:
        blobs_dir = settings.get('blobs_dir', fallback=None)
        if blobs_dir:
            tfa_dir = os.path.join(blobs_dir, 'tfa')
    if tfa_dir and os.path.exists(tfa_dir):
        # Add TF-A directory to binman search path
        current = os.environ.get('BINMAN_INDIRS', '')
        if current:
            env['BINMAN_INDIRS'] = f'{current}:{tfa_dir}'
        else:
            env['BINMAN_INDIRS'] = tfa_dir
    elif tfa_dir:
        tout.warning(f'TF-A directory not found: {tfa_dir}')
    else:
        tout.warning(f'No TF-A directory configured for {board}')


def pytest_env(board):
    """Set up environment variables for pytest testing

    Args:
        board (str): Board name

    Returns:
        dict: Environment variables that were set (not the full environment)
    """
    env = {}

    if 'riscv' in board:
        setup_riscv_env(board, env)

    if 'sbsa' in board:
        setup_sbsa_env(board, env)

    # Build PATH with hooks directories
    path_parts = []

    # Local hooks from U-Boot tree take precedence
    uboot_dir = get_uboot_dir()
    if uboot_dir:
        local_hooks = os.path.join(uboot_dir, 'test/hooks/bin')
        if os.path.exists(local_hooks):
            path_parts.append(local_hooks)

    # Then configured hooks from settings
    hooks = settings.get('test_hooks')
    if hooks and os.path.exists(hooks):
        hooks_bin = os.path.join(hooks, 'bin')
        if os.path.exists(hooks_bin):
            hooks = hooks_bin
        path_parts.append(hooks)

    if path_parts:
        current_path = os.environ.get('PATH', '')
        env['PATH'] = ':'.join(path_parts) + ':' + current_path

    return env


def list_qemu_boards():
    """List available QEMU boards using buildman

    Returns:
        list: Sorted list of QEMU board names
    """
    uboot_dir = get_uboot_dir()
    orig_dir = os.getcwd()
    try:
        if uboot_dir:
            os.chdir(uboot_dir)
        result = command.run_pipe([['buildman', '-nv', 'qemu']], capture=True,
                                   capture_stderr=True, raise_on_error=False)
    finally:
        os.chdir(orig_dir)

    if result.return_code != 0:
        return []

    boards = []
    for line in result.stdout.splitlines():
        # Board names are on indented lines after "qemu : N boards"
        if line.startswith('   '):
            boards.extend(line.split())
    return sorted(boards)


def build_pytest_cmd(args):
    """Build the pytest command line

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        list: Command and arguments to run
    """
    cmd = ['./test/py/test.py']
    cmd.extend(['-B', args.board])

    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{args.board}'
    cmd.extend(['--build-dir', build_dir])

    if args.build:
        cmd.append('--build')

    cmd.append('--buildman')

    cmd.extend(['--id', 'na'])

    if args.test_spec:
        # Convert Class.method or Class:method to "Class and method" for -k matching
        specs = []
        for s in args.test_spec:
            # Match: CapitalWord followed by : or . then test_word
            s = re.sub(r'([A-Z]\w+)[.:](\w+)', r'\1 and \2', s)
            specs.append(s)
        cmd.extend(['-k', ' '.join(specs)])

    if args.timeout != 300:
        cmd.extend(['-o', f'faulthandler_timeout={args.timeout}'])

    cmd.append('-q')
    if args.quiet:
        cmd.extend(['--no-header', '--quiet-hooks'])
    if args.show_output:
        cmd.append('-s')
    if args.timing is not None:
        cmd.extend(['--timing', '--durations=0',
                    f'--durations-min={args.timing}'])
    if args.setup_only:
        cmd.append('--setup-only')
    if args.persist:
        cmd.append('--persist')

    return cmd


def parse_hook_config(config_path):
    """Parse shell variable assignments from a hook config file

    Args:
        config_path (str): Path to the config file

    Returns:
        dict: Dictionary of variable names to values
    """
    variables = {}
    if not os.path.exists(config_path):
        return variables

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Match variable assignments: name=value or name="value"
            match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$', line)
            if match:
                name, value = match.groups()
                # Remove surrounding quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                variables[name] = value
    return variables


def expand_vars(value, env):
    """Expand shell-style variable references in a string

    Args:
        value (str): String potentially containing ${VAR} references
        env (dict): Environment variables for substitution

    Returns:
        str: String with variables expanded
    """
    def replace_var(match):
        var_name = match.group(1)
        return env.get(var_name, f'${{{var_name}}}')

    return re.sub(r'\$\{([^}]+)\}', replace_var, value)


def get_board_config(board):
    """Get the hook configuration for a board

    Args:
        board (str): Board name

    Returns:
        dict: Configuration with keys like 'console_impl', 'qemu_binary',
            'qemu_machine', 'qemu_extra_args', 'qemu_kernel_args', etc.,
            or None if not found
    """
    hooks = settings.get('test_hooks')
    if not hooks:
        tout.error('test_hooks not configured in settings')
        return None

    hooks_bin = os.path.join(hooks, 'bin')
    if not os.path.exists(hooks_bin):
        tout.error(f'Hooks bin directory not found: {hooks_bin}')
        return None

    hostname = socket.gethostname()
    board_id = 'na'  # Default board identifier

    # Build config file path
    cfg = os.path.join(hooks_bin, hostname, f'conf.{board}_{board_id}')

    # Resolve symlinks
    if os.path.islink(cfg):
        cfg = os.path.realpath(cfg)

    if not os.path.exists(cfg):
        tout.error(f'Config file not found: {cfg}')
        return None

    return parse_hook_config(cfg)


def get_qemu_command(board, args):
    """Build the QEMU command line from hook-config files

    Args:
        board (str): Board name
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        str: QEMU command line, or None if not a QEMU board
    """
    config = get_board_config(board)
    if not config:
        return None

    # Check if this is a QEMU board
    if config.get('console_impl') != 'qemu':
        tout.warning(f'Board {board} is not a QEMU board '
                     f'(console_impl={config.get("console_impl")})')
        return None

    # Build environment for variable expansion
    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{board}'

    env = os.environ.copy()
    env['U_BOOT_BUILD_DIR'] = build_dir
    env['UBOOT_TRAVIS_BUILD_DIR'] = build_dir

    # Add OPENSBI if configured
    pytest_vars = pytest_env(board)
    env.update(pytest_vars)

    # Extract QEMU command components
    qemu_binary = config.get('qemu_binary', 'qemu-system-unknown')
    qemu_machine = config.get('qemu_machine', '')
    qemu_extra_args = config.get('qemu_extra_args', '')
    qemu_kernel_args = config.get('qemu_kernel_args', '')

    # Expand variables
    qemu_extra_args = expand_vars(qemu_extra_args, env)
    qemu_kernel_args = expand_vars(qemu_kernel_args, env)

    # Build command line
    cmd_parts = [qemu_binary]
    if qemu_extra_args:
        cmd_parts.append(qemu_extra_args)
    cmd_parts.append(f'-M {qemu_machine}')
    if qemu_kernel_args:
        cmd_parts.append(qemu_kernel_args)

    return ' '.join(cmd_parts)


def find_test_file(uboot_dir, test_spec):
    """Find the Python test file for a test spec

    Args:
        uboot_dir (str): U-Boot source directory
        test_spec (str): Test spec like 'TestExt4l:test_unlink' or 'test_ext4l'

    Returns:
        tuple: (file_path, class_name, method_name) or (None, None, None)
    """
    # Parse spec: TestClass:method or TestClass.method or just test_file
    match = re.match(r'(?:Test)?(\w+?)(?:[:.](\w+))?$', test_spec, re.IGNORECASE)
    if not match:
        return None, None, None

    base_name = match.group(1).lower()
    method = match.group(2)

    # Search for test file
    test_dirs = [
        os.path.join(uboot_dir, 'test/py/tests'),
        os.path.join(uboot_dir, 'test/py/tests/test_fs'),
    ]

    for test_dir in test_dirs:
        test_file = os.path.join(test_dir, f'test_{base_name}.py')
        if os.path.exists(test_file):
            class_name = f'Test{base_name.capitalize()}'
            # Handle names like 'ext4l' -> 'TestExt4l'
            if '_' not in base_name:
                class_name = f'Test{base_name[0].upper()}{base_name[1:]}'
            return test_file, class_name, method

    return None, None, None


def parse_c_test_call(test_file, class_name, method_name):
    """Parse a Python test file to extract the C test command

    Looks for ubman.run_command() calls in the test method.

    Args:
        test_file (str): Path to Python test file
        class_name (str): Test class name
        method_name (str): Test method name

    Returns:
        tuple: (suite, c_test_name, arg_key, fixture_name) or (None, None, None, None)
    """
    with open(test_file, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, None, None, None

    # Find the class and method
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    # Look for ubman.run_command() calls
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Call):
                            # Check if it's ubman.run_command()
                            if (isinstance(stmt.func, ast.Attribute) and
                                stmt.func.attr == 'run_command'):
                                # Get the command string
                                if stmt.args and isinstance(stmt.args[0],
                                                            ast.JoinedStr):
                                    # f-string - extract parts
                                    return extract_fstring_cmd(stmt.args[0])

    return None, None, None, None


def extract_fstring_cmd(fstring_node):
    """Extract C test info from an f-string AST node

    Args:
        fstring_node: ast.JoinedStr node

    Returns:
        tuple: (suite, c_test_name, arg_key, fixture_name) or (None, None, None, None)
    """
    # Build the command pattern from f-string parts
    parts = []
    arg_name = None
    for value in fstring_node.values:
        if isinstance(value, ast.Constant):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            # This is the variable part like {ext4_image}
            if isinstance(value.value, ast.Name):
                arg_name = value.value.id
            parts.append('{VAR}')

    cmd = ''.join(parts)
    # Parse: 'ut -f fs fs_test_ext4l_unlink_norun fs_image={VAR}'
    match = re.match(r'ut\s+-\w+\s+(\w+)\s+(\w+)\s+(\w+)=', cmd)
    if match:
        suite = match.group(1)
        c_test = match.group(2)
        arg_key = match.group(3)
        return suite, c_test, arg_key, arg_name

    return None, None, None, None


def get_fixture_path(uboot_dir, test_file, fixture_name):
    """Get the path created by a fixture

    Args:
        uboot_dir (str): U-Boot source directory
        test_file (str): Path to Python test file
        fixture_name (str): Name of the fixture (e.g., 'ext4_image')

    Returns:
        str: Path to fixture output, or None
    """
    # Parse the test file to find the fixture
    with open(test_file, 'r', encoding='utf-8') as f:
        source = f.read()

    # Look for the image path pattern in fixture (may span multiple lines)
    # e.g., image_path = os.path.join(u_boot_config.persistent_data_dir,
    #                                 'ext4l_test.img')
    match = re.search(r"image_path\s*=.*?['\"](\w+\.img)['\"]", source, re.DOTALL)
    if match:
        img_name = match.group(1)
        build_dir = settings.get('build_dir', '/tmp/b')
        return os.path.join(build_dir, 'sandbox', 'persistent-data', img_name)

    return None


def run_c_test(args):
    """Run just the C test part of a pytest test

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    if not args.test_spec:
        tout.error('Test spec required for -C (e.g., TestExt4l:test_unlink)')
        return 1

    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return 1

    test_spec = args.test_spec[0]
    test_file, class_name, method_name = find_test_file(uboot_dir, test_spec)
    if not test_file:
        tout.error(f"Cannot find test file for '{test_spec}'")
        return 1

    if not method_name:
        tout.error(f"Method name required (e.g., TestExt4l:test_unlink)")
        return 1

    result = parse_c_test_call(test_file, class_name, method_name)
    if not result[0]:
        tout.error(f"Cannot find C test command in {class_name}.{method_name}")
        return 1

    suite, c_test, arg_key, fixture_name = result

    # Get fixture output path
    fixture_path = get_fixture_path(uboot_dir, test_file, fixture_name)
    if not fixture_path:
        tout.error(f"Cannot determine fixture path for '{fixture_name}'")
        return 1

    if not os.path.exists(fixture_path):
        tout.error(f"Setup not done: {fixture_path} not found")
        tout.error(f"Run first: ut py -SP {test_spec}")
        return 1

    # Build and run the sandbox command
    build_dir = settings.get('build_dir', '/tmp/b')
    sandbox = os.path.join(build_dir, 'sandbox', 'u-boot')
    if not os.path.exists(sandbox):
        tout.error('Sandbox not built - run: utool b sandbox')
        return 1

    ut_cmd = f'ut -Em {suite} {c_test} {arg_key}={fixture_path}'
    cmd = [sandbox, '-T', '-F', '-c', ut_cmd]

    print(f"{sandbox} -T -F -c '{ut_cmd}'", flush=True)
    if args.dry_run:
        return 0

    result = command.run_pipe([cmd], capture=False, raise_on_error=False)
    return result.return_code


def do_pytest(args):  # pylint: disable=too-many-return-statements,too-many-branches
    """Handle pytest command - run pytest tests for U-Boot

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    if args.list_boards:
        boards = list_qemu_boards()
        if boards:
            tout.notice('Available QEMU boards:')
            for board in boards:
                print(f'  {board}')
        else:
            tout.warning('No QEMU boards found (is buildman configured?)')
        return 0

    # Handle -C option: run just the C test part
    if getattr(args, 'c_test', False):
        return run_c_test(args)

    board = args.board or os.environ.get('b')
    if not board:
        tout.error('Board is required: use -b BOARD or set $b (use -l to list)')
        return 1
    args.board = board

    # Handle --show-cmd option
    if getattr(args, 'show_cmd', False):
        qemu_cmd = get_qemu_command(board, args)
        if qemu_cmd:
            print(qemu_cmd)
            return 0
        return 1

    if not setup_uboot_dir():
        return 1

    # Check for u-boot executable unless building
    if not args.build:
        if args.build_dir:
            build_dir = args.build_dir
        else:
            base_dir = settings.get('build_dir', '/tmp/b')
            build_dir = f'{base_dir}/{board}'
        uboot_exe = os.path.join(build_dir, 'u-boot')
        if not os.path.exists(uboot_exe):
            tout.error(f'U-Boot not built: {uboot_exe}')
            tout.error('Use -B to build first, or run: utool b ' + board)
            return 1

    tout.info(f'Running pytest for board: {args.board}')

    pytest_vars = pytest_env(args.board)
    cmd = build_pytest_cmd(args)

    env = os.environ.copy()
    env.update(pytest_vars)
    result = exec_cmd(cmd, args, env=env, capture=False)

    if result is None:  # dry-run
        return 0

    if result.return_code != 0:
        if not args.quiet:
            tout.error('pytest failed')
        return result.return_code

    if not args.quiet:
        tout.notice('pytest passed')
    return 0
