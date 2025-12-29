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

- ``-s, --suites``: Enable SUITES
- ``-p, --pytest [BOARD]``: Enable PYTEST (optionally specify board name)
- ``-t, --test-spec SPEC``: Override test specification (e.g. "not sleep",
  "test_ofplatdata")
- ``-w, --world``: Enable WORLD
- ``-l, --sjg [BOARD]``: Set SJG_LAB (optionally specify board)
- ``-f, --force``: Force push (required when rewriting branch history)
- ``-0, --null``: Skip all CI stages (no builds/tests run, MR can merge
  immediately)
- ``-m, --merge``: Create merge request using cover letter from patch series
- ``-d, --dest BRANCH``: Destination branch name (default: current branch name)

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

Pytest Subcommand
-----------------

The ``pytest`` command (alias ``py``) runs U-Boot's test.py test framework. It
automatically sets up environment variables and build directories. Set
``export b=sandbox`` (or another board) to avoid needing ``-b`` each time.

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
    uman py -b sandbox

    # Run specific test pattern (no quotes needed for multi-word specs)
    uman py -b sandbox test_dm or test_env

    # Quiet mode with timing info
    uman py -qb sandbox -t

    # Build before testing, use custom timeout
    uman py -b sandbox --build -T 600

    # Dry run to see command and environment
    uman --dry-run py -b qemu-riscv64

**Options**:

- ``test_spec``: Test specification using pytest -k syntax (positional)
- ``-b, --board BOARD``: Board name to test (required, or set ``$b``)
- ``-l, --list``: List available QEMU boards
- ``-q, --quiet``: Quiet mode - only show build errors, progress, and result
- ``-T, --timeout SECS``: Test timeout in seconds (default: 300)
- ``-t, --timing [SECS]``: Show test timing (default min: 0.1s)
- ``-s, --show-output``: Show all test output in real-time (pytest -s)
- ``--build``: Build U-Boot before running tests
- ``--build-dir DIR``: Override build directory
- ``-c, --show-cmd``: Show QEMU command line without running tests
- ``-S, --setup-only``: Run only fixture setup (create test images) without tests
- ``-P, --persist``: Persist test artifacts (do not clean up after tests)
- ``-C, --c-test``: Run just the C test part (assumes setup done with -SP)

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

    # List available suites
    uman test -s

    # List tests in a suite
    uman test -l dm

**Options**:

- ``-l, --list``: List available tests
- ``-s, --suites``: List available test suites
- ``-f, --flattree``: Use flat device tree for tests
- ``-V, --test-verbose``: Enable verbose test output
- ``-r, --results``: Show per-test pass/fail status
- ``-L, --legacy``: Use legacy result parsing (for old U-Boot)
- ``-m, --manual``: Force manual tests to run (tests with _norun suffix)

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

Self-testing
------------

The tool includes comprehensive self-tests using the U-Boot test framework::

    # Run all self-tests
    uman selftest

    # Run a specific test
    uman selftest test_ci_subcommand_parsing

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
