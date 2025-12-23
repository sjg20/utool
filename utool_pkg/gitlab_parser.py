# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""GitLab CI file parser for utool

This module parses the GitLab CI YAML file to extract valid values
for SJG_LAB roles and TEST_PY_BD boards.
"""

import os
import re
from pathlib import Path

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def find_gitlab_ci_file():
    """Find the GitLab CI file in the U-Boot source tree

    Returns:
        str: Path to .gitlab-ci.yml file, or None if not found
    """
    # Try common locations relative to current directory
    candidates = [
        '../u/.gitlab-ci.yml',
        '../../u/.gitlab-ci.yml',
        '/home/sglass/u/.gitlab-ci.yml'
    ]

    for candidate in candidates:
        path = Path(candidate).resolve()
        if path.exists():
            return str(path)

    return None


def parse_gitlab_ci_file(filepath=None):
    """Parse GitLab CI file to extract valid values using YAML parser

    Args:
        filepath (str): Path to .gitlab-ci.yml file. If None, auto-detect.

    Returns:
        dict: Dictionary containing:
            - 'roles': List of valid SJG_LAB role values
            - 'boards': List of valid TEST_PY_BD board values
    """
    if filepath is None:
        filepath = find_gitlab_ci_file()

    if not filepath or not os.path.exists(filepath):
        return {'roles': [], 'boards': []}

    roles = set()
    boards = set()

    # Read file content once
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Try YAML parsing first if available
    if YAML_AVAILABLE:
        data = yaml.safe_load(content)

        # Walk through all jobs to find ROLE and TEST_PY_BD values
        for _, job_config in data.items():
            if not isinstance(job_config, dict):
                continue

            # Look for variables section
            variables = job_config.get('variables')
            if not isinstance(variables, dict):
                continue

            if 'ROLE' in variables:
                roles.add(str(variables['ROLE']))
            if 'TEST_PY_BD' in variables:
                boards.add(str(variables['TEST_PY_BD']).strip('"'))

    # If YAML is not available, use regex fallback
    else:
        # Extract ROLE values - look for "ROLE: value" patterns
        role_matches = re.findall(r'^[ \t]*ROLE:\s*([a-zA-Z0-9_-]+)',
                                content, re.MULTILINE)
        roles.update(role_matches)

        # Extract TEST_PY_BD values - look for "TEST_PY_BD: value" patterns
        board_matches = re.findall(r'^[ \t]*TEST_PY_BD:\s*"([^"]+)"',
                                 content, re.MULTILINE)
        boards.update(board_matches)

    return {
        'roles': sorted(list(roles)),
        'boards': sorted(list(boards))
    }


def validate_sjg_value(value, gitlab_data=None):
    """Validate an SJG_LAB value against GitLab CI file

    Args:
        value (str): SJG_LAB value to validate
        gitlab_data (dict): Parsed GitLab data, or None to auto-parse

    Returns:
        bool: True if value is valid, False otherwise
    """
    if value == '1':  # Special case: '1' is always valid
        return True

    if gitlab_data is None:
        gitlab_data = parse_gitlab_ci_file()

    return value in gitlab_data['roles']


def validate_pytest_value(value, gitlab_data=None):
    """Validate a pytest/TEST_PY_BD value against GitLab CI file

    Args:
        value (str): TEST_PY_BD value to validate
        gitlab_data (dict): Parsed GitLab data, or None to auto-parse

    Returns:
        bool: True if value is valid, False otherwise
    """
    if value == '1':  # Special case: '1' is always valid
        return True

    if gitlab_data is None:
        gitlab_data = parse_gitlab_ci_file()

    return value in gitlab_data['boards']


def get_sjg_choices():
    """Get list of valid SJG_LAB choices for argument parser

    Returns:
        list: Valid SJG_LAB role names
    """
    gitlab_data = parse_gitlab_ci_file()
    choices = ['1'] + gitlab_data['roles']  # '1' is always valid
    return choices


def get_pytest_choices():
    """Get list of valid pytest choices for argument parser

    Returns:
        list: Valid TEST_PY_BD board names
    """
    gitlab_data = parse_gitlab_ci_file()
    choices = ['1'] + gitlab_data['boards']  # '1' is always valid
    return choices
