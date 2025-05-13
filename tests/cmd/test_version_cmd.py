import json
from unittest import mock

import pytest
import yaml
from hetznerinv import __version__ as package_version
from hetznerinv.cli import app  # Main app to invoke subcommands
from typer.testing import CliRunner

runner = CliRunner()


def test_version_cmd_simple():
    """Test 'version' command with no options."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert package_version in result.stdout
    assert "Python Version:" not in result.stdout  # Should not be present without --all


def test_version_cmd_all_text():
    """Test 'version --all --output text' command."""
    result = runner.invoke(app, ["version", "--all", "--output", "text"])
    assert result.exit_code == 0
    # VERSION.text() produces a single line like "Running 0.2.2, with CPython 3.12.8, on Linux"
    assert package_version in result.stdout
    assert "CPython" in result.stdout # Check for part of Python version detail
    assert "Linux" in result.stdout   # Check for part of system info
    assert "Git SHA:" not in result.stdout # VERSION.text() does not include "Git SHA:" prefix
    # If git sha is included by VERSION.text(), it's usually just the sha or "N/A"
    # We can check if the output contains the version string and some system details.
    # A more robust check might involve parsing VERSION.text() if its format is very strict.
    # For now, checking for substrings is okay.
    # The original VERSION.text() from ant31box.version.Version.text() is
    # "Running {app_version}, with {python_impl} {python_ver}, on {os_name}"
    # It does not include "Version:", "Python Version:", "System Info:", "Git SHA:" as separate labels.
    # The _echo_text_output in cmd/version.py calls VERSION.text() directly.
    # So the assertions should match the output of VERSION.text()
    assert f"Running {package_version}" in result.stdout
    assert "with CPython" in result.stdout # Example, depends on test environment
    assert "on Linux" in result.stdout     # Example, depends on test environment


def test_version_cmd_simple_json():
    """Test 'version --output json' command."""
    result = runner.invoke(app, ["version", "--output", "json"])
    assert result.exit_code == 0
    try:
        data = json.loads(result.stdout)
        assert data == {"version": package_version}
    except json.JSONDecodeError:
        pytest.fail("Output was not valid JSON.")


def test_version_cmd_all_json():
    """Test 'version --all --output json' command."""
    result = runner.invoke(app, ["version", "--all", "--output", "json"])
    assert result.exit_code == 0
    try:
        data = json.loads(result.stdout)
        assert data["version"] == package_version
        assert "python" in data
        assert "system" in data
        assert "sha" in data
    except json.JSONDecodeError:
        pytest.fail("Output was not valid JSON.")


def test_version_cmd_simple_yaml():
    """Test 'version --output yaml' command."""
    result = runner.invoke(app, ["version", "--output", "yaml"])
    assert result.exit_code == 0
    try:
        data = yaml.safe_load(result.stdout)
        assert data == {"version": package_version}
    except yaml.YAMLError:
        pytest.fail("Output was not valid YAML.")


def test_version_cmd_all_yaml():
    """Test 'version --all --output yaml' command."""
    result = runner.invoke(app, ["version", "--all", "--output", "yaml"])
    assert result.exit_code == 0
    try:
        data = yaml.safe_load(result.stdout)
        assert data["version"] == package_version
        assert "python" in data
        assert "system" in data
        assert "sha" in data
    except yaml.YAMLError:
        pytest.fail("Output was not valid YAML.")


@mock.patch("hetznerinv.cmd.version.yaml", None)
def test_version_cmd_yaml_output_pyyaml_not_installed():
    """Test 'version --output yaml' when PyYAML is not installed."""
    # By default, runner.invoke mixes stderr into stdout if an exception occurs
    # and stdout/stderr are not explicitly separated by bytes.
    result = runner.invoke(app, ["version", "--output", "yaml"])
    assert result.exit_code == 1
    assert "Error: PyYAML is required for YAML output." in result.stdout


def test_version_cmd_default_output_format_with_all():
    """Test that --all defaults to JSON if no --output is specified."""
    result_all_no_output = runner.invoke(app, ["version", "--all"])
    # The default for --all is text, as per current implementation in version.py
    # _echo_text_output(all_info) is called if effective_output_format is text
    # effective_output_format = OutputFormat.json if all_info else OutputFormat.text
    # This logic was changed in version.py, let's re-verify.
    # Current version.py: effective_output_format = OutputFormat.json if all_info else OutputFormat.text
    # So, if --all is true, it should default to JSON.
    assert result_all_no_output.exit_code == 0
    try:
        data = json.loads(result_all_no_output.stdout)
        assert data["version"] == package_version
        assert "python" in data # Check for detailed content typical of JSON --all
    except json.JSONDecodeError:
        pytest.fail("--all without --output should default to JSON and be valid JSON.")

def test_version_cmd_default_output_format_without_all():
    """Test that no flags defaults to text if no --output is specified."""
    result_no_flags = runner.invoke(app, ["version"])
    assert result_no_flags.exit_code == 0
    assert result_no_flags.stdout.strip() == package_version # Simple text output
