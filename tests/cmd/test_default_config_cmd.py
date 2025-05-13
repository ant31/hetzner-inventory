from pathlib import Path
from unittest import mock

import pytest
import yaml  # For loading the output
from hetznerinv.cli import app  # Main app to invoke subcommands
from typer.testing import CliRunner

runner = CliRunner()

def test_default_config_cmd_simple():
    """Test 'default-config' command with no options."""
    result = runner.invoke(app, ["default-config"])
    assert result.exit_code == 0
    try:
        data = yaml.safe_load(result.stdout)
        assert isinstance(data, dict)
        assert "name" in data
        assert data["name"] == "hetznerinv" # Default name from HetznerConfigSchema
        assert "hetzner_credentials" in data
        assert "hetzner" in data
        assert "cluster_prefix" in data["hetzner"]
        assert data["hetzner"]["cluster_prefix"] == "a" # Default
    except yaml.YAMLError:
        pytest.fail("Output was not valid YAML.")


def test_default_config_cmd_with_custom_file(tmp_path: Path):
    """Test 'default-config --config <file>' command with a custom config file."""
    custom_config_content = """
name: custom_app_name
hetzner:
  cluster_prefix: "k"
  domain_name: "custom.example.com"
  ssh_fingerprints:
    - "fp1"
hetzner_credentials:
  robot_user: "custom_robot"
"""
    custom_config_file = tmp_path / "custom.yaml"
    custom_config_file.write_text(custom_config_content)

    result = runner.invoke(app, ["default-config", "--config", str(custom_config_file)])
    assert result.exit_code == 0
    try:
        data = yaml.safe_load(result.stdout)
        assert isinstance(data, dict)
        # Values from custom file
        assert data["name"] == "custom_app_name"
        assert data["hetzner"]["cluster_prefix"] == "k"
        assert data["hetzner"]["domain_name"] == "custom.example.com"
        assert data["hetzner"]["ssh_fingerprints"] == ["fp1"]
        assert data["hetzner_credentials"]["robot_user"] == "custom_robot"

        # Default values not in custom file should still be present
        assert "robot_password" in data["hetzner_credentials"] # Default is ""
        assert data["hetzner_credentials"]["robot_password"] == ""
        assert "update_server_names_in_cloud" in data["hetzner"] # Default is False
        assert data["hetzner"]["update_server_names_in_cloud"] is False

    except yaml.YAMLError:
        pytest.fail("Output was not valid YAML.")


def test_default_config_cmd_with_empty_custom_file(tmp_path: Path):
    """Test 'default-config --config <file>' with an empty custom config file."""
    custom_config_file = tmp_path / "empty.yaml"
    custom_config_file.write_text("") # Empty file

    result = runner.invoke(app, ["default-config", "--config", str(custom_config_file)])
    assert result.exit_code == 0 # Should still succeed and output defaults
    try:
        data = yaml.safe_load(result.stdout)
        assert isinstance(data, dict)
        assert data["name"] == "hetznerinv"
        assert data["hetzner"]["cluster_prefix"] == "a"
    except yaml.YAMLError:
        pytest.fail("Output was not valid YAML.")


def test_default_config_cmd_with_non_dict_custom_file(tmp_path: Path):
    """Test 'default-config --config <file>' with a custom file that is not a dict."""
    custom_config_file = tmp_path / "list_config.yaml"
    custom_config_file.write_text("- item1\n- item2") # YAML list, not a dict

    result = runner.invoke(app, ["default-config", "--config", str(custom_config_file)])
    assert result.exit_code == 1
    # When mix_stderr is True (default), stderr content goes to stdout/output
    assert "Error: Configuration file" in result.stdout
    assert "must contain a YAML mapping (dictionary)" in result.stdout


@mock.patch("hetznerinv.cmd.default_config.yaml", None)
def test_default_config_cmd_pyyaml_not_installed():
    """Test 'default-config' when PyYAML is not installed."""
    result = runner.invoke(app, ["default-config"]) # mix_stderr=True by default
    assert result.exit_code == 1
    assert "Error: PyYAML is required to output the configuration." in result.stdout
