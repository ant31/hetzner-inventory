import pytest

from hetznerinv.config import Config, HetznerCredentials, config


def test_default_config_loading():
    """Test that the default configuration loads without errors."""
    try:
        cfg = config(reload=True)  # Ensure fresh load
        assert cfg is not None
        assert isinstance(cfg, Config)
        assert cfg.conf.name == "hetznerinv"  # Check a default value
        assert cfg.hetzner is not None
        assert cfg.hetzner_credentials is not None
    except Exception as e:
        pytest.fail(f"Default configuration loading failed: {e}")


def test_hetzner_credentials_get_hcloud_token():
    """Test the get_hcloud_token method logic."""
    # Case 1: Only default token is set
    creds1 = HetznerCredentials(hcloud_token="default_token")
    assert creds1.get_hcloud_token("production") == "default_token"
    assert creds1.get_hcloud_token("staging") == "default_token"

    # Case 2: Only environment-specific token is set
    creds2 = HetznerCredentials(hcloud_tokens={"production": "prod_token"})
    assert creds2.get_hcloud_token("production") == "prod_token"
    assert creds2.get_hcloud_token("staging") is None  # No default, no staging specific

    # Case 3: Both default and environment-specific tokens are set
    creds3 = HetznerCredentials(
        hcloud_token="default_token", hcloud_tokens={"production": "prod_token"}
    )
    assert creds3.get_hcloud_token("production") == "prod_token"  # Prod token takes precedence
    assert creds3.get_hcloud_token("staging") == "default_token"  # Staging falls back to default

    # Case 4: Environment-specific token is set, but for a different environment
    creds4 = HetznerCredentials(
        hcloud_token="default_token", hcloud_tokens={"development": "dev_token"}
    )
    assert creds4.get_hcloud_token("production") == "default_token"  # Falls back to default
    assert creds4.get_hcloud_token("development") == "dev_token"

    # Case 5: No tokens are set
    creds5 = HetznerCredentials()
    assert creds5.get_hcloud_token("production") is None
    assert creds5.get_hcloud_token("staging") is None

    # Case 6: Env specific token is empty string, default is set
    creds6 = HetznerCredentials(
        hcloud_token="default_token", hcloud_tokens={"production": ""}
    )
    # An empty string token for an env is still a "set" token, so it should return that, not fallback.
    assert creds6.get_hcloud_token("production") == ""
    assert creds6.get_hcloud_token("staging") == "default_token"


def test_config_loading_with_path(tmp_path):
    """Test loading configuration from a YAML file."""
    config_content = """
name: test_hetznerinv
hetzner_credentials:
  robot_user: test_user
  hcloud_token: file_default_token
  hcloud_tokens:
    production: file_prod_token
hetzner:
  cluster_prefix: "z"
  domain_name: "example.com"
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(config_content)

    cfg = config(path=str(config_file), reload=True)

    assert cfg.conf.name == "test_hetznerinv"
    assert cfg.hetzner_credentials.robot_user == "test_user"
    assert cfg.hetzner_credentials.get_hcloud_token("production") == "file_prod_token"
    assert cfg.hetzner_credentials.get_hcloud_token("staging") == "file_default_token" # Falls back to file default
    assert cfg.hetzner.cluster_prefix == "z"
    assert cfg.hetzner.domain_name == "example.com"

    # Test that default values not in the file are still present
    assert cfg.hetzner.update_server_names_in_cloud is False # Default from HetznerInventoryConfig
    assert cfg.hetzner.ssh_identity_file == "~/.ssh/id_rsa" # Default from HetznerInventoryConfig
