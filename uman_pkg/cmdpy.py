# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Pytest command for running U-Boot tests

This module handles the 'pytest' subcommand which runs U-Boot's pytest
test framework.
"""

import ast
import glob
import math
import os
import re
import socket
import subprocess
import time

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tools
from u_boot_pylib import tout

from uman_pkg import build as build_mod
from uman_pkg import settings
from uman_pkg.cmdtest import get_sandbox_path
from uman_pkg.util import exec_cmd, get_uboot_dir

# Pattern to parse test spec: TestClass:method or TestClass.method or just name
RE_TEST_SPEC = re.compile(r'(?:Test)?(\w+?)(?:[:.](\w+))?$', re.IGNORECASE)

# Glob pattern to find test files (use with .format(name=...))
GLOB_TEST = 'test/py/**/test_{name}.py'


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
        # Convert Class:method or Class::method to "Class and method" for -k
        spec = ' '.join(args.test_spec)
        spec = spec.replace('::', ' and ').replace(':', ' and ')
        cmd.extend(['-k', spec])

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
    if args.gdbserver:
        cmd.extend(['--gdbserver', args.gdbserver])
    if args.exitfirst:
        cmd.append('-x')
    if not args.full:
        cmd.append('--no-full')

    # Add extra pytest arguments (after --)
    if args.extra_args:
        cmd.extend(args.extra_args)

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


def find_test(uboot_dir, test_spec):
    """Find the Python test file for a test spec

    Args:
        uboot_dir (str): U-Boot source directory
        test_spec (str): Test spec like 'TestExt4l:test_unlink' or 'test_ext4l'

    Returns:
        tuple: (file_path, class_name, method_name) or (None, None, None)
    """
    match = RE_TEST_SPEC.match(test_spec)
    if not match:
        return None, None, None

    base_name = match.group(1).lower()
    method = match.group(2)

    # Search for test file
    pattern = os.path.join(uboot_dir, GLOB_TEST.format(name=base_name))
    matches = glob.glob(pattern, recursive=True)
    if matches:
        test_file = matches[0]
        class_name = f'Test{base_name.capitalize()}'
        # Handle names like 'ext4l' -> 'TestExt4l'
        if '_' not in base_name:
            class_name = f'Test{base_name[0].upper()}{base_name[1:]}'
        return test_file, class_name, method

    return None, None, None


def find_run_ut_call(method_node):
    """Find a run_ut() call in a method's AST

    Args:
        method_node (ast.FunctionDef): Method node to search

    Returns:
        ast.Call or None: The run_ut() call node, or None if not found
    """
    for stmt in ast.walk(method_node):
        if not isinstance(stmt, ast.Call):
            continue
        if not isinstance(stmt.func, ast.Attribute):
            continue
        if stmt.func.attr == 'run_ut':
            return stmt
    return None


def parse_c_test_call(source, class_name, method_name):
    """Parse Python test source to extract the C test command

    Looks for ubman.run_ut() calls in the test method.

    Args:
        source (str): Python source code
        class_name (str): Test class name
        method_name (str): Test method name

    Returns:
        tuple: (suite, c_test_name, arg_key, fixture_name) or (None,)*4
    """
    tree = ast.parse(source)

    # Find the class and method
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name != method_name:
                continue
            call = find_run_ut_call(item)
            if call:
                return extract_run_ut_args(call)

    return None, None, None, None


def extract_run_ut_args(call_node):
    """Extract C test info from a run_ut() call AST node

    Parses: ubman.run_ut('fs', 'fs_test_ext4l_probe', fs_image=ext4_image)

    Args:
        call_node (ast.Call): AST Call node for run_ut()

    Returns:
        tuple: (suite, c_test_name, arg_key, fixture_name) or (None,)*4
    """
    # Need at least 2 positional args: suite and test name
    if len(call_node.args) < 2:
        return None, None, None, None

    # Extract suite (first arg)
    if not isinstance(call_node.args[0], ast.Constant):
        return None, None, None, None
    suite = call_node.args[0].value

    # Extract test name (second arg) - add _norun suffix
    if not isinstance(call_node.args[1], ast.Constant):
        return None, None, None, None
    c_test = call_node.args[1].value + '_norun'

    # Extract first keyword argument (e.g., fs_image=ext4_image)
    if not call_node.keywords:
        return None, None, None, None

    kw = call_node.keywords[0]
    arg_key = kw.arg
    if isinstance(kw.value, ast.Name):
        fixture_name = kw.value.id
    else:
        return None, None, None, None

    return suite, c_test, arg_key, fixture_name


def get_fixture_path(test_file):
    """Get the path created by a fixture

    Args:
        test_file (str): Path to Python test file

    Returns:
        str: Path to fixture output, or None
    """
    source = tools.read_file(test_file, binary=False)

    # Look for the image path pattern in fixture (may span multiple lines)
    # e.g., image_path = os.path.join(u_boot_config.persistent_data_dir,
    #                                 'ext4l_test.img')
    match = re.search(r"image_path\s*=.*?['\"](\w+\.img)['\"]", source,
                      re.DOTALL)
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

    sandbox = get_sandbox_path()
    if not sandbox:
        tout.error('Sandbox not built - run: uman b sandbox')
        return 1

    test_name = args.test_spec[0]
    test_file, class_name, method = find_test(uboot_dir, test_name)
    if not test_file:
        tout.error(f"Cannot find test file for '{test_name}'")
        return 1

    if not method:
        tout.error('Method name required (e.g., TestExt4l:test_unlink)')
        return 1

    # Get fixture output path
    fixture_path = get_fixture_path(test_file)
    if not fixture_path:
        tout.error('Cannot determine fixture path')
        return 1

    if not os.path.exists(fixture_path):
        tout.error(f'Setup not done: run uman py -SP {test_name}')
        return 1

    source = tools.read_file(test_file, binary=False)
    suite, c_test, arg_key, _ = parse_c_test_call(source, class_name, method)
    if not suite:
        tout.error(f'Cannot find C test command in {class_name}.{method}')
        return 1

    ut_cmd = f'ut -Em {suite} {c_test} {arg_key}={fixture_path}'
    cmd = [sandbox, '-T', '-F', '-c', ut_cmd]

    result = exec_cmd(cmd, args)
    if not result:
        return 0

    print(result.stdout, end='')

    # Check test actually ran (wasn't skipped)
    match = re.search(r'Result: (PASS|FAIL|SKIP):', result.stdout)
    if not match:
        tout.error('Test did not produce a result - check setup')
        return 1
    if match.group(1) == 'SKIP':
        tout.error('Test was skipped - check test flags')
        return 1

    return result.return_code


def run_with_gdb(args):
    """Launch gdb to connect to an existing gdbserver

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    # Get the U-Boot executable path
    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{args.board}'
    uboot_exe = os.path.join(build_dir, 'u-boot')

    if not os.path.exists(uboot_exe):
        tout.error(f'U-Boot executable not found: {uboot_exe}')
        return 1

    # Get gdbserver channel
    channel = args.gdbserver or 'localhost:1234'

    # Build gdb command
    gdb_cmd = [
        'gdb-multiarch',
        uboot_exe,
        '-ex', f'target remote {channel}',
        '-ex', 'continue',
    ]

    tout.info(f"Running: {' '.join(gdb_cmd)}")

    # Parse host:port from channel
    if ':' in channel:
        host, port = channel.rsplit(':', 1)
        port = int(port)
    else:
        host, port = 'localhost', int(channel)

    def port_alive():
        """Check if gdbserver port is accepting connections"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect((host, port))
            sock.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False

    # Run gdb in a loop, reconnecting when server restarts
    reconnect_timeout = 5  # seconds to wait for server after gdb disconnects
    while True:
        # pylint: disable=consider-using-with
        proc = subprocess.Popen(gdb_cmd)

        # Wait for gdb to connect before monitoring
        time.sleep(1)

        # Monitor for server to become available (indicates U-Boot restarted)
        # While gdb is connected, the port is occupied so port_alive() is False
        # When U-Boot restarts, gdbserver listens again and port_alive() is True
        try:
            while proc.poll() is None:
                if port_alive():
                    # Server is accepting connections - U-Boot restarted
                    tout.notice('Server restarted, reconnecting...')
                    proc.terminate()
                    proc.wait()
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            break

        # gdb exited - wait briefly for server to come back
        if proc.returncode is not None:
            start = time.time()
            while time.time() - start < reconnect_timeout:
                if port_alive():
                    tout.notice('Server restarted, reconnecting...')
                    break
                time.sleep(0.2)
            else:
                # Server didn't come back, tests finished
                tout.notice('Server not responding, exiting')
                break

    return 0


def collect_tests(args):
    """Collect all tests using pytest --collect-only

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        list: Ordered list of test node IDs, or None on error
    """
    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{args.board}-bisect'

    cmd = ['./test/py/test.py', '-B', args.board, '--build-dir', build_dir,
           '--buildman', '--id', 'na', '--collect-only', '-q']

    if args.build:
        cmd.append('--build')

    if args.test_spec:
        spec = ' '.join(args.test_spec)
        cmd.extend(['-k', spec])

    result = command.run_pipe([cmd], capture=True, capture_stderr=True,
                              raise_on_error=False)
    if result.return_code != 0:
        tout.error('Failed to collect tests')
        if result.stderr:
            print(result.stderr)
        return None

    tests = []
    for line in result.stdout.splitlines():
        line = line.strip()
        # Test lines contain :: (e.g., test_ut.py::TestUt::test_dm)
        if '::' in line and not line.startswith('<'):
            tests.append(line)
    return tests


def node_to_name(node_id):
    """Extract test name from a pytest node ID for use with -k

    Args:
        node_id (str): Full node ID like 'tests/test_ut.py::test_ut[ut_dm_foo]'

    Returns:
        str: Test name suitable for -k, e.g. 'ut_dm_foo'
    """
    # Extract the part in brackets if present (parameterized tests)
    if '[' in node_id and node_id.endswith(']'):
        return node_id[node_id.index('[') + 1:-1]
    # Otherwise use the method name after the last ::
    if '::' in node_id:
        return node_id.split('::')[-1]
    return node_id


def pollute_run(tests, target, args, env):
    """Run a subset of tests followed by the target test

    Args:
        tests (list): Tests to run before target (full node IDs)
        target (str): Target test that may fail (full node ID)
        args (argparse.Namespace): Arguments from cmdline
        env (dict): Environment variables

    Returns:
        bool: True if target test failed, False if it passed
    """
    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{args.board}-pollute'

    # Convert node IDs to test names and join with "or" for -k
    all_tests = tests + [target]
    names = [node_to_name(t) for t in all_tests]
    spec = ' or '.join(names)

    cmd = ['./test/py/test.py', '-B', args.board, '--build-dir', build_dir,
           '--buildman', '--id', 'na', '-q', '-k', spec]

    total = len(all_tests)
    done = 0
    # pytest result chars: . pass, F fail, s skip, E error, x xfail, X xpass
    result_chars = '.FsExX'

    # Run with Popen to show progress as tests complete
    # pylint: disable=consider-using-with
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    while True:
        char = proc.stdout.read(1)
        if not char:
            break
        if char.decode('utf-8', errors='replace') in result_chars:
            done += 1
            tout.progress(f'    {done}/{total}', trailer='')
    tout.clear_progress()
    proc.wait()
    return proc.returncode != 0


def do_pollute(args):
    """Find which test pollutes the target test

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    target = args.pollute

    # Find U-Boot source directory
    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return 1

    # Change to U-Boot directory if needed
    if uboot_dir != os.getcwd():
        os.chdir(uboot_dir)

    tout.notice('Collecting tests...')
    tests = collect_tests(args)
    if tests is None:
        return 1

    # Find target in test list
    target_idx = None
    for i, test in enumerate(tests):
        if target in test:
            target_idx = i
            target = test  # Use full test name
            break

    if target_idx is None:
        tout.error(f"Target test '{args.pollute}' not found in collection")
        tout.info('Available tests containing that string:')
        for test in tests:
            if args.pollute.lower() in test.lower():
                print(f'  {test}')
        return 1

    tout.notice(f"Found {len(tests)} tests, target '{target}' at position "
                f'{target_idx + 1}')

    if target_idx == 0:
        tout.error('Target is the first test - nothing can pollute it')
        return 1

    candidates = tests[:target_idx]
    pytest_vars = pytest_env(args.board)
    env = os.environ.copy()
    env.update(pytest_vars)

    # Verify target passes alone
    tout.notice('Verifying target passes alone...')
    if pollute_run([], target, args, env):
        tout.error('Target test fails when run alone - not a pollution issue')
        return 1
    tout.notice('  OK')

    # Verify target fails with all candidates
    tout.notice('Verifying target fails with all prior tests...')
    if not pollute_run(candidates, target, args, env):
        tout.error('Target test passes with all prior tests - cannot reproduce')
        return 1
    tout.notice('  FAIL (confirmed)')

    # Binary search
    steps = math.ceil(math.log2(len(candidates))) if candidates else 0
    step = 0

    tout.notice(f'Searching for polluter in {len(candidates)} candidate tests...')
    while len(candidates) > 1:
        step += 1
        mid = len(candidates) // 2
        first_half = candidates[:mid]

        print(f'  Step {step}/{steps}: {len(first_half)} tests...')
        if pollute_run(first_half, target, args, env):
            tout.notice('  -> FAIL (polluter in first half)')
            candidates = first_half
        else:
            tout.notice('  -> PASS (polluter in second half)')
            candidates = candidates[mid:]

    if not candidates:
        tout.error('No polluter found - may need multiple tests to trigger')
        return 1

    polluter = candidates[0]

    # Final verification
    print(f'  Verifying {node_to_name(polluter)}...')
    if pollute_run([polluter], target, args, env):
        tout.notice('  -> FAIL (confirmed)')
    else:
        tout.notice('  -> PASS (inconclusive - may need multiple tests)')
        return 1

    polluter_name = node_to_name(polluter)
    target_name = node_to_name(target)
    red = '\033[31m'
    reset = '\033[0m'
    tout.notice(
        f'\nFound: {target_name} polluted by {red}{polluter_name}{reset}')
    tout.notice(f'  Run: uman py -B {args.board} "{polluter} or {target}"')
    return 0


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
    if args.c_test:
        return run_c_test(args)

    board = args.board or os.environ.get('b')
    if not board:
        tout.error('Board is required: use -B BOARD or set $b (use -l to list)')
        return 1
    args.board = board

    # Handle --pollute option
    if args.pollute:
        return do_pollute(args)

    # Handle --show-cmd option
    if args.show_cmd:
        qemu_cmd = get_qemu_command(board, args)
        if qemu_cmd:
            print(qemu_cmd)
            return 0
        return 1

    # Find U-Boot source directory
    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return 1

    # Change to U-Boot directory if needed
    if uboot_dir != os.getcwd():
        tout.info(f'Changing to U-Boot directory: {uboot_dir}')
        os.chdir(uboot_dir)

    tout.info(f'Running pytest for board: {args.board}')

    # Handle -G: set gdbserver if not already set
    if args.gdb and not args.gdbserver:
        args.gdbserver = 'localhost:1234'

    # Build with um if requested, rather than letting pytest do it
    if args.build:
        if not build_mod.build_board(args.board, args.dry_run):
            return 1
        args.build = False  # Don't build again in pytest

    # Show -G command hint when using -g (not in dry-run mode)
    if args.gdbserver and not args.gdb and not args.dry_run:
        tout.notice(f'In another terminal: um py -G -B {args.board}')

    pytest_vars = pytest_env(args.board)
    cmd = build_pytest_cmd(args)

    env = os.environ.copy()
    env.update(pytest_vars)

    # Handle -G: just launch gdb to connect to existing gdbserver
    if args.gdb:
        return run_with_gdb(args)

    result = exec_cmd(cmd, args.dry_run, env=env, capture=False)

    if result is None:  # dry-run
        return 0

    if result.return_code != 0:
        if not args.quiet:
            tout.error('pytest failed')
        return result.return_code

    if not args.quiet:
        tout.notice('pytest passed')
    return 0
