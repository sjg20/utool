.. SPDX-License-Identifier: GPL-2.0+
.. Copyright 2025 Canonical Ltd
.. Written by Simon Glass <simon.glass@canonical.com>

utool - U-Boot Automation Tool
==============================

This is a a simple tool to handle common tasks when developing U-Boot.

Installation
------------

Install dependencies::

    pip install -r requirements.txt

Usage
-----

::

    # Push with specific tests
    utool ci -s -p -l rpi4

    # Dry-run to see what would be executed
    utool --dry-run ci -w

    # Run tests
    utool test

CI Options
----------

- ``-s, --suites``: Enable SUITES
- ``-p, --pytest [BOARD]``: Enable PYTEST (optionally specify board name)
- ``-t, --test-spec SPEC``: Override test specification (e.g. "not sleep", "test_ofplatdata")
- ``-w, --world``: Enable WORLD
- ``-l, --sjg [BOARD]``: Set SJG_LAB (optionally specify board)
- ``-f, --force``: Force push
- ``-0, --null``: Set all CI vars to 0
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
    utool ci -d my-feature       # Push current branch to 'my-feature' on 'ci' remote
    utool ci -d cherry-abc123    # Push current branch to 'cherry-abc123' on 'ci' remote

**Note**: Use board names (like ``coreboot``, ``sandbox``) to target all jobs
for that board, or exact job names (like ``"sandbox with clang test.py"``) to
target specific job variants. Use ``-p help`` or ``-l help`` to see all
available choices.

Merge Request Creation
----------------------

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

GitLab API Behavior and Variable Limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

3. **Workflow Solution - Commit Message Tags**: To control MR pipelines, use
   commit message tags:

   - ``[skip-suites]`` - Skip test_suites stage
   - ``[skip-pytest]`` - Skip pytest/test.py stages
   - ``[skip-world]`` - Skip world_build stage
   - ``[skip-sjg]`` - Skip sjg-lab stage

4. **Recommended Workflow**:

   - For **parameterized variables** (``-l rpi4``, ``-p sandbox``): Use regular
     ``utool ci`` first, create MR manually later
   - For **simple skip flags** (``-0``, ``-w``): Use commit message tags with
     ``utool ci --merge``

5. **Single Commit Support**: For branches with only one commit, the tool uses
   the commit subject as MR title and commit body as description, eliminating
   the need for a cover letter.

6. **API Integration**: Uses pickman's GitLab API wrapper for MR creation and
   python-gitlab for pipeline management.

Testing
-------

The tool includes comprehensive tests using the U-Boot test framework::

    # Run all tests
    utool test

    # Run specific test
    utool test test_ci_subcommand_parsing
