.. SPDX-License-Identifier: GPL-2.0+
.. Copyright 2025 Canonical Ltd
.. Written by Simon Glass <simon.glass@canonical.com>

utool - U-Boot Automation Tool
==============================

This is a a simple tool to handle common tasks when developing U-Boot.

Usage
-----

::

    # Push with specific tests
    python -m utool_pkg ci -s -p -l rpi4

    # Dry-run to see what would be executed
    python -m utool_pkg --dry-run ci -w

    # Run tests
    python -m utool_pkg test

CI Options
----------

- ``-s, --suites``: Enable SUITES
- ``-p, --pytest [SPEC]``: Enable PYTEST (optionally specify test spec)
- ``-w, --world``: Enable WORLD
- ``-l, --sjg [BOARD]``: Set SJG_LAB (optionally specify board)
- ``-f, --force``: Force push
- ``-0, --null``: Set all CI vars to 0

Testing
-------

The tool includes comprehensive tests using the U-Boot test framework::

    # Run all tests
    python -m utool_pkg test

    # Run specific test
    python -m utool_pkg test test_ci_subcommand_parsing
