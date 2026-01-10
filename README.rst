.. SPDX-License-Identifier: GPL-2.0+
.. Copyright 2025 Canonical Ltd
.. Written by Simon Glass <simon.glass@canonical.com>

uman - U-Boot Manager
=====================

This is a simple tool to handle common tasks when developing U-Boot,
including pushing to CI, running tests, and setting up firmware dependencies.

Subcommands
-----------

``ci``
    Push current branch to GitLab CI with configurable test stages

``pytest`` (alias: ``py``)
    Run U-Boot's test.py framework with automatic environment setup

``config`` (alias: ``cfg``)
    Examine U-Boot .config files

``git`` (alias: ``g``)
    Git rebase helpers for interactive rebasing

``selftest`` (alias: ``st``)
    Run uman's own test suite

``setup``
    Download and build firmware blobs needed for testing (OpenSBI, TF-A, etc.)

Installation
------------

Install dependencies::

    pip install -r requirements.txt

Settings
--------

Uman stores settings in ``~/.uman``, created on first run. Key settings
include build directories, firmware paths, and test hook locations. See the
Configuration_ section below for details.

CI Subcommand
-------------

The ``ci`` subcommand pushes the current branch to GitLab CI for testing. It
configures which test stages to run and can optionally create a GitLab
merge request (MR).

The basic idea is that you create a branch with your changes, add a patman
cover letter to the HEAD commit (ideally) and then type::

    uman ci -m

This pushes your branch to CI and creates an MR for the changes. It will also
kick off various builds and tests, as defined by ``.gitlab-ci.yml``.

This is all very well, but you could almost as easily push the branch with git
and then create an MR manually. But uman provides a few more features. It
allows you to select which CI stages run, for cases where you are iterating on
a particular problem, or know that your change only affects a certain part of
the CI process. For lab and pytests, it also allows you to run on just a single
board or test. You can even set the test-spec to use.

Some simple examples::

    # Push and run only on the SJG lab with the 'rpi4' board
    uman ci -l rpi4

    # Dry-run to see what would be executed
    uman --dry-run ci -w

**Options**

- ``-0, --null``: Skip all CI stages (no builds/tests run, MR can merge
  immediately)
- ``-a, --all``: Run all CI stages including lab
- ``-d, --dest BRANCH``: Destination branch name (default: current branch name)
- ``-f, --force``: Force push (required when rewriting branch history)
- ``-l, --sjg [BOARD]``: Set SJG_LAB (optionally specify board)
- ``-m, --merge``: Create merge request using cover letter from patch series
- ``-p, --pytest [BOARD]``: Enable PYTEST (optionally specify board name)
- ``-s, --suites``: Enable SUITES
- ``-t, --test-spec SPEC``: Override test specification (e.g. "not sleep",
  "test_ofplatdata")
- ``-w, --world``: Enable WORLD

Pytest Targeting Examples
~~~~~~~~~~~~~~~~~~~~~~~~~

::

    # Show all available pytest targets and lab names
    uman ci -p help
    uman ci -l help

    # Run all pytest jobs
    uman ci -p

    # Target by board name (runs any job with that TEST_PY_BD)
    uman ci -p coreboot
    uman ci -p sandbox

    # Target by exact job name (runs only that specific job)
    uman ci -p "sandbox with clang test.py"
    uman ci -p "sandbox64 test.py"

    # Override test specification for targeted job
    uman ci -p coreboot -t "test_ofplatdata"
    uman ci -p "sandbox with clang test.py" -t "not sleep"

    # Run all pytest jobs with custom test specification
    uman ci -p -t "not sleep"

    # Push to different branch names (always to 'ci' remote)
    uman ci                     # Push to same branch name on 'ci' remote
    uman ci -d my-feature       # Push to 'my-feature' on 'ci' remote

**Note**: Use board names (like ``coreboot``, ``sandbox``) to target all jobs
for that board, or exact job names (like ``"sandbox with clang test.py"``) to
target specific job variants. Use ``-p help`` or ``-l help`` to see all
available choices.

Merge Request Creation
~~~~~~~~~~~~~~~~~~~~~~

The tool can create GitLab merge requests with automated pipeline creation::

    # Create merge request
    uman ci --merge

    # Create merge request with specific CI stages (tags added automatically)
    uman ci --merge -0        # Adds [skip-suites] [skip-pytest] etc.
    uman ci --merge --suites  # Adds [skip-pytest] [skip-world] [skip-sjg]
    uman ci --merge --world   # Adds [skip-suites] [skip-pytest] [skip-sjg]

**Important**: Merge requests only support stage-level control (which stages
run), not fine-grained selection of specific boards or test specifications.
For precise targeting like ``-p coreboot`` or ``-t "test_ofplatdata"``, use
regular CI pushes instead of merge requests.

Git Subcommand
--------------

The ``git`` command (alias ``g``) provides helpers for interactive rebasing,
making it easier to step through commits during development.

**Actions**:

- ``gr [N]``: Open interactive rebase editor (to upstream or HEAD~N)
- ``ra``: Abort the current rebase (stashes changes, shows recovery info)
- ``rb``: Rebase from beginning - stops at first commit for editing
- ``rf N``: Rebase last N commits, stopping at first for editing
- ``rp N``: Rebase to upstream, stop at patch N for editing (0 = first)
- ``rn [N]``: Continue rebase to next commit (see below for details)
- ``rc``: Continue rebase (git rebase --continue)
- ``rs``: Skip current commit (git rebase --skip)

The ``rn`` command behaves differently depending on context:

- At an edit point: sets the next (or Nth) commit to 'edit' and continues
- After resolving a conflict: continues and stops at the current commit
- With unresolved conflicts: errors out (resolve conflicts first)

**Examples**::

    # Open interactive rebase editor (to upstream)
    uman git gr

    # Rebase last 5 commits interactively (opens editor)
    uman git gr 5

    # Rebase to upstream, stop at first commit for editing
    uman git rb

    # Rebase last 3 commits, stop at first
    uman git rf 3

    # Rebase to upstream, stop at patch 2 for editing
    uman git rp 2

    # Rebase to upstream, stop at first commit (same as rb)
    uman git rp 0

    # Continue rebase, setting next commit to edit
    uman git rn

    # Skip 2 commits, set the 3rd to edit
    uman git rn 3

    # Continue rebase (shortcut for git rebase --continue)
    uman git rc

    # Skip current commit (shortcut for git rebase --skip)
    uman git rs

**Workflow Example**:

To edit commit HEAD~2 (the third commit from HEAD)::

    uman git rf 3       # Rebase last 3 commits, stops at HEAD~2
    # ... make changes ...
    git add <files> && git commit --amend --no-edit
    uman git rn         # Continue to next commit (HEAD~1) and edit
    # ... or just: uman git rc

The number in ``rf N`` is "how many commits to include in rebase", not "which
commit to edit". So ``rf 3`` includes HEAD~2, HEAD~1, HEAD in the rebase,
stopping at HEAD~2 (the first/oldest in the range).

**Conflict Workflow**:

When a rebase hits a conflict::

    uman git rf 3       # Rebase last 3 commits, stops at HEAD~2
    # ... make changes that cause a conflict with the next commit ...
    git add <files> && git commit --amend --no-edit
    uman git rc         # Continue - hits conflict
    # ... resolve conflict ...
    git add <files>
    uman git rn         # Continue and stop at this commit
    # ... verify the resolution ...
    uman git rn         # Continue to next commit and edit

Using ``rn`` after resolving a conflict stops at the current commit, giving you
a chance to verify the resolution before moving on.

Pytest Subcommand
-----------------

The ``pytest`` command (alias ``py``) runs U-Boot's test.py test framework. It
automatically sets up environment variables and build directories. Set
``export b=sandbox`` (or another board) to avoid needing ``-B`` each time.

It builds U-Boot automatically before testing, uses ``--buildman`` for
cross-compiler setup, sets ``OPENSBI`` for RISC-V boards, and adds U-Boot test
hooks to PATH.

::

    # List available QEMU boards
    $ uman py -l
    Available QEMU boards:
      qemu-riscv64
      qemu-x86_64
      qemu_arm64
      ...

    # Run tests for a board (board is required, or use $b env var)
    uman py -B sandbox

    # Run specific test pattern (no quotes needed for multi-word specs)
    uman py -B sandbox test_dm or test_env

    # Quiet mode with timing info
    uman py -qB sandbox -t

    # Build before testing, disable timeout
    uman py -B sandbox -bT

    # Dry run to see command and environment
    uman --dry-run py -B qemu-riscv64

    # Pass extra arguments to pytest (after --)
    uman py -B sandbox TestFsBasic -- --fs-type ext4

**Options**:

- ``test_spec``: Test specification using pytest -k syntax (positional)
- ``-b, --build``: Build U-Boot before running tests (uses um build)
- ``-B, --board BOARD``: Board name to test (required, or set ``$b``)
- ``-c, --show-cmd``: Show QEMU command line without running tests
- ``-C, --c-test``: Run just the C test part (assumes setup done with -SP);
  use with -s to show live output
- ``-f, --full``: Run both live-tree and flat-tree tests (default: live-tree only)
- ``-F, --find PATTERN``: Find tests matching PATTERN and show full IDs
- ``-g``: Run sandbox under gdbserver at localhost:1234
- ``-G, --gdb``: Launch gdb-multiarch and connect to an existing gdbserver
- ``-l, --list``: List available QEMU and sandbox boards
- ``-L, --lto``: Enable LTO when building (use with -b)
- ``-P, --persist``: Persist test artifacts (do not clean up after tests)
- ``-q, --quiet``: Quiet mode - only show build errors, progress, and result
- ``-s, --show-output``: Show all test output in real-time (pytest -s)
- ``-S, --setup-only``: Run only fixture setup (create test images) without tests
- ``-t, --timing [SECS]``: Show test timing (default min: 0.1s)
- ``-T, --no-timeout``: Disable test timeout
- ``-x, --exitfirst``: Stop on first test failure
- ``--pollute TEST``: Find which test pollutes TEST
- ``--build-dir DIR``: Override build directory
- ``--gdbserver CHANNEL``: Run sandbox under gdbserver (e.g., localhost:5555)

**Running C Tests Directly**:

Some pytest tests are thin wrappers around C unit tests. The ``-C`` option lets
you run just the C test part after setting up fixtures once::

    # First, set up the test fixtures (creates filesystem images etc.)
    uman py -SP TestExt4l:test_unlink

    # Run only the C test (fast iteration during development)
    uman py -C TestExt4l:test_unlink

    # Show output while running
    uman py -C TestExt4l:test_unlink -s

This is useful when iterating on C code - you avoid the pytest overhead and
fixture setup on each run. The ``-C`` option:

- Parses the Python test to find the ``ubman.run_ut()`` call
- Extracts the C test command (suite, test name, fixture path)
- Runs sandbox directly with the ``ut`` command
- Shows a summary: ``Results: 1 passed, 0 failed, 0 skipped in 0.21s``

Without ``-s``, output is only shown on failure.

**Finding Test Pollution**:

When a test fails only after other tests have run, use ``--pollute`` to find the
polluting test::

    # Find which test causes dm_test_host_base to fail
    uman py -xB sandbox --pollute dm_test_host_base "not slow"

The pollution search process:

1. Collects all tests using ``--collect-only`` (pytest's default order)
2. Finds the target test's position in the list
3. Takes all tests **before** the target as candidates
4. Verifies the target passes alone, fails with all candidates
5. Binary search: runs first half of candidates + target
   - If target fails → polluter is in first half
   - If target passes → polluter is in second half
6. Repeats until single polluter found

Example: tests ``[A, B, C, D, E, F]`` with ``F`` failing only after others run:

- Candidates: ``[A, B, C, D, E]``
- Step 1: run ``A B C F`` → PASS → polluter in ``[D, E]``
- Step 2: run ``D F`` → FAIL → polluter is ``D``
- Verify: run ``D F`` → FAIL → confirmed

Each bisect step extracts test names from node IDs and uses ``-k`` with an
"or" expression (e.g., ``-k "ut_dm_foo or ut_dm_bar"``). This preserves
pytest's execution order while selecting specific tests.

The final verification step confirms the polluter by running just polluter +
target and checking it fails. This ensures the result is correct.

Uses a separate build directory (``sandbox-bisect``) to avoid conflicts.

**Debugging with GDB**:

Use ``-g`` to start pytest under gdbserver, then ``-G`` in another terminal
to connect gdb::

    # Terminal 1: Start pytest with gdbserver
    uman py -b -g -B sandbox bootstd or luks
    # Shows: In another terminal: um py -G -B sandbox

    # Terminal 2: Connect with gdb
    um py -G -B sandbox

**Test Hooks Search Order**:

The pytest command searches for test hooks in the following order:

1. **Local hooks** from the U-Boot source tree: ``$USRC/test/hooks/bin``
2. **Configured hooks** from settings: ``test_hooks`` in ``~/.uman``

Local hooks take precedence, so you can test with hooks from the U-Boot tree
being tested without modifying your global configuration. The ``bin``
subdirectory is automatically appended if present.

**Debugging QEMU Configuration**:

Use ``-c/--show-cmd`` to display the QEMU command line without running tests::

    uman py -b qemu-riscv64 -c

This parses the hook configuration files and expands variables like
``${U_BOOT_BUILD_DIR}`` and ``${OPENSBI}``, showing exactly what QEMU command
would be executed. This helps diagnose issues with missing firmware, incorrect
paths, or misconfigured hooks.

**Source Directory**:

The pytest command must be run from a U-Boot source tree. If you're not in a
U-Boot directory, set the ``USRC`` environment variable to point to your U-Boot
source::

    export USRC=~/u
    uman py -b sandbox    # Works from any directory

Test Subcommand
---------------

The ``test`` command (alias ``t``) runs U-Boot's sandbox unit tests directly,
without going through pytest. This is faster for quick iteration on C code.

::

    # Run all tests
    uman test

    # Run specific suite
    uman test dm

    # Run specific test
    uman test dm.acpi

    # Run test using pytest-style name (ut_<suite>_<test>)
    uman test ut_bootstd_bootflow

    # List available suites
    uman test -s

    # List tests in a suite
    uman test -l dm

**Options**:

- ``-b, --build``: Build before running tests
- ``-B, --board BOARD``: Board to build/test (default: sandbox)
- ``-f, --full``: Run both live-tree and flat-tree tests (default: live-tree only)
- ``-l, --list``: List available tests
- ``-L, --legacy``: Use legacy result parsing (for old U-Boot)
- ``-m, --manual``: Force manual tests to run (tests with _norun suffix)
- ``-r, --results``: Show per-test pass/fail status
- ``-s, --suites``: List available test suites
- ``-V, --test-verbose``: Enable verbose test output

Config Subcommand
-----------------

The ``config`` command (alias ``cfg``) provides tools for examining and
modifying U-Boot configuration::

    # Grep .config for a pattern (case-insensitive regex)
    uman config -B sandbox -g VIDEO
    um cfg -g DM_TEST

    # Resync defconfig from current .config
    uman config -B sandbox -s

The sync option runs ``make <board>_defconfig``, then ``make savedefconfig``,
shows a colored diff of changes, and copies the result back to
``configs/<board>_defconfig``.

**Options**:

- ``-B, --board BOARD``: Board name (required; or set ``$b``)
- ``-g, --grep PATTERN``: Grep .config for PATTERN (regex, case-insensitive)
- ``-s, --sync``: Resync defconfig from .config
- ``--build-dir DIR``: Override build directory

Build Subcommand
----------------

The ``build`` command (alias ``b``) builds U-Boot for a specified board::

    # Build for sandbox
    uman build sandbox

    # Build with LTO enabled
    uman build sandbox -L

    # Force reconfiguration
    uman build sandbox -f

    # Build specific target
    uman build sandbox -t u-boot.bin

    # Build with gprof profiling
    uman build sandbox --gprof

    # Bisect to find first commit that breaks the build
    uman build sandbox --bisect

    # Build with verbose make output
    uman build sandbox -a V=1

**Options**:

- ``-a, --make-arg ARG``: Pass argument to make (can use multiple times)
- ``-f, --force-reconfig``: Force reconfiguration
- ``-F, --fresh``: Delete build directory first
- ``--bisect``: Bisect to find first commit that breaks the build (assumes
  HEAD fails and upstream builds)
- ``--gprof``: Enable gprof profiling (sets GPROF=1)
- ``-I, --in-tree``: Build in source tree, not separate directory
- ``-j, --jobs JOBS``: Number of parallel jobs (passed to make)
- ``-L, --lto``: Enable LTO
- ``-o, --output-dir DIR``: Override output directory
- ``-O, --objdump``: Write disassembly of u-boot and SPL ELFs
- ``-s, --size``: Show size of u-boot and SPL ELFs
- ``-t, --target TARGET``: Build specific target (e.g. u-boot.bin)
- ``-T, --trace``: Enable function tracing (FTRACE=1)

Setup Subcommand
----------------

The ``setup`` command downloads and installs dependencies needed for testing
various architectures::

    # Install all components
    uman setup

    # List available components
    uman setup -l

    # Install specific component
    uman setup qemu
    uman setup opensbi
    uman setup tfa
    uman setup xtensa

    # Force reinstall
    uman setup opensbi -f

**Options**:

- ``-f, --force``: Force rebuild even if already built
- ``-l, --list``: List available components

**Components**:

- ``qemu``: Install QEMU packages for all architectures (arm, riscv, x86, ppc,
  xtensa). Uses ``apt-get`` with sudo.
- ``opensbi``: Download pre-built OpenSBI firmware for RISC-V (both 32-bit and
  64-bit) from GitHub releases.
- ``tfa``: Clone and build ARM Trusted Firmware for QEMU SBSA board. Requires
  ``aarch64-linux-gnu-`` cross-compiler.
- ``xtensa``: Download Xtensa dc233c toolchain from foss-xtensa releases and
  configure ``~/.buildman``.

**Installed locations** (configurable in ``~/.uman``):

- OpenSBI: ``~/dev/blobs/opensbi/fw_dynamic.bin`` (64-bit),
  ``fw_dynamic_rv32.bin`` (32-bit)
- TF-A: ``~/dev/blobs/tfa/bl1.bin``, ``fip.bin``
- Xtensa: ``~/dev/blobs/xtensa/2020.07/xtensa-dc233c-elf/``

.. _Configuration:

Configuration
-------------

Settings are stored in ``~/.uman`` (created on first run)::

    [DEFAULT]
    # Build directory for U-Boot out-of-tree builds
    build_dir = /tmp/b

    # Directory for firmware blobs (OpenSBI, TF-A, etc.)
    blobs_dir = ~/dev/blobs

    # OPENSBI firmware paths for RISC-V testing (built by 'uman setup')
    opensbi = ~/dev/blobs/opensbi/fw_dynamic.bin
    opensbi_rv32 = ~/dev/blobs/opensbi/fw_dynamic_rv32.bin

    # TF-A firmware directory for ARM SBSA testing
    tfa_dir = ~/dev/blobs/tfa

    # U-Boot test hooks directory
    test_hooks = /vid/software/devel/ubtest/u-boot-test-hooks

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

``UBOOT_TOOLS``
    Path to U-Boot tools directory containing Python libraries (u_boot_pylib,
    patman, buildman, etc.). This is used for importing Python modules.
    Default: ``~/u/tools``

``USRC``
    Path to U-Boot source tree to work in. If not set, uman expects to be run
    from within a U-Boot source tree.

These are separate: ``UBOOT_TOOLS`` specifies where to find Python imports,
while ``USRC`` specifies the U-Boot source tree to build/test.

Self-testing
------------

The tool includes comprehensive self-tests using the U-Boot test framework::

    # Run all self-tests
    uman selftest

    # Run a specific test
    uman selftest test_ci_subcommand_parsing

**Options**:

- ``-N, --no-capture``: Disable capturing of console output in tests
- ``-X, --test-preserve-dirs``: Preserve and display test-created directories

Technical Notes
---------------

GitLab API Behaviour
~~~~~~~~~~~~~~~~~~~~

Key findings about GitLab merge request and pipeline creation:

1. **Variable Scope Limitation**: GitLab CI variables passed via
   ``git push -o ci.variable="FOO=bar"`` only apply to **push pipelines**.
   Merge request pipelines created automatically when opening an MR do **not**
   inherit these variables - they always use the default values from
   ``.gitlab-ci.yml``.

2. **Pipeline Types**:

   - **Push Pipeline**: Created by ``git push``, inherits CI variables from
     push options
   - **Merge Request Pipeline**: Created automatically when MR is opened, uses
     default YAML variables only

3. **Workflow Solution - MR Description Tags**: To control MR pipelines, use
   tags in the MR description:

   - ``[skip-suites]`` - Skip test_suites stage
   - ``[skip-pytest]`` - Skip pytest/test.py stages
   - ``[skip-world]`` - Skip world_build stage
   - ``[skip-sjg]`` - Skip sjg-lab stage

4. **Recommended Workflow**:

   - For **parameterised variables** (``-l rpi4``, ``-p sandbox``): Use regular
     ``uman ci`` first, create MR manually later
   - For **simple skip flags** (``-0``, ``-w``): Use MR description tags with
     ``uman ci --merge``

5. **Single Commit Support**: For branches with only one commit, the tool uses
   the commit subject as MR title and commit body as description, eliminating
   the need for a cover letter.

6. **API Integration**: Uses pickman's GitLab API wrapper for MR creation and
   python-gitlab for pipeline management.

Terminology
~~~~~~~~~~~

'Merge request' (two words, no hyphen) is standard prose, being a request to
merge.
