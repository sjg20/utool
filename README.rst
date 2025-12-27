.. SPDX-License-Identifier: GPL-2.0+
.. Copyright 2025 Canonical Ltd
.. Written by Simon Glass <simon.glass@canonical.com>

utool - U-Boot Automation Tool
==============================

This is a simple tool to handle common tasks when developing U-Boot,
including pushing to CI, running tests, and setting up firmware dependencies.

Subcommands
-----------

``build`` (alias: ``b``)
    Build U-Boot for a specified board using buildman

``ci``
    Push current branch to GitLab CI with configurable test stages

``pytest`` (alias: ``py``)
    Run U-Boot's test.py framework with automatic environment setup

``selftest`` (alias: ``st``)
    Run utool's own test suite

``setup``
    Download and build firmware blobs needed for testing (OpenSBI, TF-A, etc.)

Installation
------------

Install dependencies::

    pip install -r requirements.txt

Settings
--------

utool stores settings in ``~/.utool``, created on first run. Key settings
include build directories, firmware paths, and test hook locations. See the
Configuration_ section below for details.

CI Subcommand
-------------

The ``ci`` subcommand pushes the current branch to GitLab CI for testing. It
configures which test stages to run and can optionally create a Gitlab
merge request (MR).

The basic idea is that you create a branch with your changes, add a patman
cover letter to the HEAD commit (ideally) and then type:

::

    utool ci -m

This pushes your branch to CI and adds a MR for the changes. It will also kick
off various builds and tests, as defined by `.gitlab-ci.yml`.

This is all very well, but you almost as easily push the branch with git and
then create an MR manually. But utool provides a few more features. It allows
you to select which CI stages run, for cases where you are iterating on a
particular problem, or know that your change only affects a certain part of the
CI process. For lab and pytests, it also allows you to run on just a single
board or test. You can even set the test-spec to use.

Some simple examples:::

    # Push and run only on the SJG lab with the 'rpi4' board
    utool ci -l rpi4

    # Dry-run to see what would be executed
    utool --dry-run ci -w

**Options**

- ``-s, --suites``: Enable SUITES
- ``-p, --pytest [BOARD]``: Enable PYTEST (optionally specify board name)
- ``-t, --test-spec SPEC``: Override test specification (e.g. "not sleep",
  "test_ofplatdata")
- ``-w, --world``: Enable WORLD
- ``-l, --sjg [BOARD]``: Set SJG_LAB (optionally specify board)
- ``-f, --force``: Force push (required when rewriting branch history)
- ``-0, --null``: Skip all CI stages (no builds/tests run, MR can merge immediately)
- ``-m, --merge``: Create merge request using cover letter from patch series
- ``-d, --dest BRANCH``: Destination branch name (default: current branch name)

Pytest Targeting Examples
~~~~~~~~~~~~~~~~~~~~~~~~~

::

    # Show all available pytest targets and lab names
    utool ci -p help
    utool ci -l help

    # Run all pytest jobs
    utool ci -p

    # Target by board name (runs any job with that TEST_PY_BD)
    utool ci -p coreboot
    utool ci -p sandbox

    # Target by exact job name (runs only that specific job)
    utool ci -p "sandbox with clang test.py"
    utool ci -p "sandbox64 test.py"

    # Override test specification for targeted job
    utool ci -p coreboot -t "test_ofplatdata"
    utool ci -p "sandbox with clang test.py" -t "not sleep"

    # Run all pytest jobs with custom test specification
    utool ci -p -t "not sleep"

    # Push to different branch names (always to 'ci' remote)
    utool ci                     # Push to same branch name on 'ci' remote
    utool ci -d my-feature       # Push to 'my-feature' on 'ci' remote
    utool ci -d cherry-abc123    # Push to 'cherry-abc123' on 'ci' remote

**Note**: Use board names (like ``coreboot``, ``sandbox``) to target all jobs
for that board, or exact job names (like ``"sandbox with clang test.py"``) to
target specific job variants. Use ``-p help`` or ``-l help`` to see all
available choices.

Merge Request Creation
~~~~~~~~~~~~~~~~~~~~~~

The tool can create GitLab merge requests with automated pipeline creation::

    # Create merge request
    utool ci --merge

    # Create merge request with specific CI stages (tags automatically added)
    utool ci --merge -0              # Adds [skip-suites] [skip-pytest] [skip-world] [skip-sjg]
    utool ci --merge --suites        # Adds [skip-pytest] [skip-world] [skip-sjg]
    utool ci --merge --world         # Adds [skip-suites] [skip-pytest] [skip-sjg]

**Important**: Merge requests only support stage-level control (which stages
run), not fine-grained selection of specific boards or test specifications.
For precise targeting like ``-p coreboot`` or ``-t "test_ofplatdata"``, use
regular CI pushes instead of merge requests.

Pytest Subcommand
-----------------

The ``pytest`` command (alias ``py``) runs U-Boot's test.py test framework. It
automatically sets up environment variables and build directories.

The basic idea is that you specify a board and optionally a test pattern::

    utool py -b sandbox test_dm

This builds U-Boot for the specified board, sets up the environment (including
cross-compiler via buildman, firmware paths for RISC-V/ARM, and test hooks),
then runs the matching tests.

Running U-Boot's test.py manually requires setting several environment variables
and remembering the correct flags. utool handles this automatically, letting you
focus on which tests to run. It also supports quiet mode for less verbose output
and timing information to identify slow tests.

Some simple examples::

    # List available QEMU boards
    utool py -l

    # Run tests for a board
    utool py -b sandbox

    # Run specific test pattern
    utool py -b sandbox test_dm
    utool py -b qemu-riscv64 not sleep

    # Quiet mode with $b environment variable as default board
    export b=sandbox
    utool py -q

    # Dry run to see command and environment
    utool --dry-run py -b qemu-riscv64 test_dm

**Options**:

- ``test_spec``: Test specification using pytest -k syntax (positional)
- ``-b, --board BOARD``: Board name to test (required, or set ``$b``)
- ``-l, --list``: List available QEMU boards
- ``-q, --quiet``: Quiet mode - only show build errors, progress, and result
- ``-T, --timeout SECS``: Test timeout in seconds (default: 300)
- ``-t, --timing [SECS]``: Show test timing (default minimum: 0.1s)
- ``-s, --show-output``: Show all test output in real-time (pytest -s)
- ``--no-build``: Skip building U-Boot (assume already built)
- ``--build-dir DIR``: Override build directory
- ``-c, --show-cmd``: Show QEMU command line without running tests

**Automatic Setup**:

- Uses ``--buildman`` flag for cross-compiler setup
- Sets ``OPENSBI`` firmware path for RISC-V boards
- Adds U-Boot test hooks to PATH (see below)
- Uses organized build directories from config file
- Builds U-Boot automatically before testing

**Test Hooks Search Order**:

The pytest command searches for test hooks in the following order:

1. **Local hooks** from the U-Boot source tree: ``$USRC/test/hooks/bin``
2. **Configured hooks** from settings: ``test_hooks`` in ``~/.utool``

Local hooks take precedence, so you can test with hooks from the U-Boot tree
being tested without modifying your global configuration. The ``bin``
subdirectory is automatically appended if present.

**Debugging QEMU Configuration**:

Use ``-c/--show-cmd`` to display the QEMU command line without running tests::

    $ utool py -b qemu-riscv64 -c
    qemu-system-riscv64 -m 1G -nographic -netdev user,id=net0,tftp=/tmp/b/qemu-riscv64
      -device virtio-net-device,netdev=net0 ... -M virt -bios /tmp/b/qemu-riscv64/u-boot

This parses the hook configuration files and expands variables like
``${U_BOOT_BUILD_DIR}`` and ``${OPENSBI}``, showing exactly what QEMU command
would be executed. This helps diagnose issues with missing firmware, incorrect
paths, or misconfigured hooks.

**Source Directory**:

The pytest command must be run from a U-Boot source tree. If you're not in a
U-Boot directory, set the ``USRC`` environment variable to point to your U-Boot
source::

    export USRC=~/u
    utool py -b sandbox    # Works from any directory

Setup Subcommand
----------------

The ``setup`` command downloads and installs dependencies needed for testing
various architectures.

Testing U-Boot on different architectures requires firmware blobs and emulators
that aren't always easy to obtain. For example, RISC-V testing needs OpenSBI
firmware, ARM SBSA needs TF-A, and QEMU packages are needed for emulation. This
command automates fetching and installing these dependencies.

::

    # Install all components
    utool setup

    # List available components
    utool setup -l

    # Install specific component
    utool setup opensbi

    # Force reinstall
    utool setup opensbi -f

**Components**:

- ``qemu``: Install QEMU packages for all architectures (arm, riscv, x86, ppc,
  xtensa). Uses ``apt-get`` with sudo.
- ``opensbi``: Download pre-built OpenSBI firmware for RISC-V (both 32-bit and
  64-bit) from GitHub releases.
- ``tfa``: Clone and build ARM Trusted Firmware for QEMU SBSA board. Requires
  ``aarch64-linux-gnu-`` cross-compiler.
- ``xtensa``: Download Xtensa dc233c toolchain from foss-xtensa releases and
  configure ``~/.buildman``.

**Installed locations** (configurable in ``~/.utool``):

- OpenSBI: ``~/dev/blobs/opensbi/fw_dynamic.bin`` (64-bit),
  ``fw_dynamic_rv32.bin`` (32-bit)
- TF-A: ``~/dev/blobs/tfa/bl1.bin``, ``fip.bin``
- Xtensa: ``~/dev/blobs/xtensa/2020.07/xtensa-dc233c-elf/``

Configuration
-------------

Settings are stored in ``~/.utool`` (created on first run)::

    [DEFAULT]
    # Build directory for U-Boot out-of-tree builds
    build_dir = /tmp/b

    # Directory for firmware blobs (OpenSBI, TF-A, etc.)
    blobs_dir = ~/dev/blobs

    # OPENSBI firmware paths for RISC-V testing (built by 'utool setup')
    opensbi = ~/dev/blobs/opensbi/fw_dynamic.bin
    opensbi_rv32 = ~/dev/blobs/opensbi/fw_dynamic_rv32.bin

    # TF-A firmware directory for ARM SBSA testing
    tfa_dir = ~/dev/blobs/tfa

    # U-Boot test hooks directory
    test_hooks = /vid/software/devel/ubtest/u-boot-test-hooks

Testing
-------

Similar to other Python tools in U-Boot, utool includes a good set of tests::

    # Run all tests
    utool selftest

    # Run specific test
    utool selftest test_ci_subcommand_parsing

Terminology
-----------

'Merge request' (two words, no hyphen) is standard prose, being a request to
merge.

Technical Notes
---------------

GitLab API Behavior and Variable Limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

3. **Workflow Solution - MR Description Tags**: To control MR pipelines, utool
   adds tags to the MR description:

   - ``[skip-suites]`` - Skip test_suites stage
   - ``[skip-pytest]`` - Skip pytest/test.py stages
   - ``[skip-world]`` - Skip world_build stage
   - ``[skip-sjg]`` - Skip sjg-lab stage

4. **Recommended Workflow**:

   - For **parameterized variables** (``-l rpi4``, ``-p sandbox``): Use regular
     ``utool ci`` first, create MR manually later
   - For **simple skip flags** (``-0``, ``-w``): Use MR description tags with
     ``utool ci --merge``

5. **Single Commit Support**: For branches with only one commit, the tool uses
   the commit subject as MR title and commit body as description, eliminating
   the need for a cover letter.

6. **API Integration**: Uses pickman's GitLab API wrapper for MR creation and
   python-gitlab for pipeline management.
