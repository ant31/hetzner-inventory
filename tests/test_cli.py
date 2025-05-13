from hetznerinv import __version__
from hetznerinv.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_app_help():
    """Test the main application help message."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert "A CLI tool for Hetzner Inventory." in result.stdout
    # Check for the command section header, accommodating Rich formatting
    assert "Commands" in result.stdout  # More general check
    assert "default-config" in result.stdout
    assert "generate" in result.stdout
    assert "version" in result.stdout


def test_app_no_args_is_help():
    """Test that invoking the app with no arguments shows help."""
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    # Typer's no_args_is_help usually shows a shorter "Usage" and then "Error: Missing command."
    # or the full help. Let's check for key elements.
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert "A CLI tool for Hetzner Inventory." in result.stdout


def test_version_command():
    """Test the 'version' command."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_command_all_json():
    """Test the 'version --all --output json' command."""
    result = runner.invoke(app, ["version", "--all", "--output", "json"])
    assert result.exit_code == 0
    assert f'"version": "{__version__}"' in result.stdout
    assert '"python"' in result.stdout
    assert '"system"' in result.stdout


def test_default_config_command():
    """Test the 'default-config' command basic invocation."""
    result = runner.invoke(app, ["default-config"])
    assert result.exit_code == 0
    assert "hetzner_credentials:" in result.stdout
    assert "hetzner:" in result.stdout
    assert "name: hetznerinv" in result.stdout # Default name


def test_default_config_command_with_file(tmp_path):
    """Test the 'default-config --config <file>' command."""
    sample_config_content = """
hetzner:
  cluster_prefix: "custom_prefix"
"""
    config_file = tmp_path / "sample_config.yaml"
    config_file.write_text(sample_config_content)

    result = runner.invoke(app, ["default-config", "--config", str(config_file)])
    assert result.exit_code == 0
    assert "cluster_prefix: custom_prefix" in result.stdout
    assert "name: hetznerinv" in result.stdout # Default name still present
    assert "domain_name: revlyt.dev" in result.stdout # Default from schema


def test_generate_command_help():
    """Test the 'generate --help' command."""
    result = runner.invoke(app, ["generate", "--help"])
    assert result.exit_code == 0
    assert "Usage: root generate [OPTIONS]" in result.stdout
    assert "Generate Hetzner inventory files and optionally an SSH configuration." in result.stdout
    assert "--config" in result.stdout
    assert "--env" in result.stdout
    assert "--gen-robot" in result.stdout
    assert "--gen-cloud" in result.stdout
    assert "--gen-ssh" in result.stdout
    assert "--all-hosts" in result.stdout
