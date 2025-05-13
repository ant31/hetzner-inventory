# pylint: disable=no-self-argument
import logging
from typing import Any

from ant31box.config import LOGGING_CONFIG as LG
from ant31box.config import BaseConfig, GConfig, GenericConfig, LoggingConfigSchema
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOGGING_CONFIG: dict[str, Any] = LG
LOGGING_CONFIG["loggers"].update({"root": {"handlers": ["default"], "level": "DEBUG", "propagate": True}})

logger: logging.Logger = logging.getLogger("hetznerinv")


class LoggingCustomConfigSchema(LoggingConfigSchema):
    log_config: dict[str, Any] | str | None = Field(default_factory=lambda: LOGGING_CONFIG)


ENVPREFIX = "HETZNER"

# New sub-models for structured configuration


class HetznerCredentials(BaseConfig):
    """
    Hetzner Robot credentials
    """

    #     model_config = SettingsConfigDict(env_prefix='HETZNER_'')
    # Hetzner Robot credentials
    robot_user: str = Field(default="")
    robot_password: str = Field(default="")

    hcloud_token: str = Field(default="", description="Default Hetzner Cloud token if not specified per environment.")
    # Hetzner Cloud token
    hcloud_tokens: dict[str, str] = Field(
        default_factory=dict,
        description="Hetzner Cloud tokens, keyed by environment name (e.g., 'production': 'token').",
    )

    def get_hcloud_token(self, env: str) -> str | None:
        """
        Retrieves the Hetzner Cloud token for the specified environment.

        It first checks the `hcloud_tokens` dictionary for an environment-specific token.
        If not found, it falls back to the general `hcloud_token`.
        Returns None if no token is found for the environment.
        """
        # Check if the environment specific token exists in the dictionary
        if env in self.hcloud_tokens:
            return self.hcloud_tokens[env]  # Return it, even if it's an empty string

        # If not found, fall back to the general hcloud_token
        return self.hcloud_token if self.hcloud_token else None


class SubnetDetail(BaseConfig):
    """Defines the structure for an entry in cluster_subnets."""

    subnet: str | None = Field(default=None, description="Subnet definition (e.g., '10.0.0.0/25').")
    start: str = Field(..., description="Starting IP address for this subnet.")  # Assuming start is always required
    privlink: bool | None = Field(default=None, description="Indicates if privlink is used for this subnet.")


class HetznerInventoryConfig(BaseConfig):
    """Configuration specific to Hetzner inventory generation."""

    ssh_fingerprints: list[str] = Field(
        default_factory=list, description="List of SSH key fingerprints for server setup."
    )
    product_options: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapping of product identifiers (e.g., server type, server ID) to option strings (e.g., 's', 'u', 'snu')."
        ),
    )
    cluster_prefix: str = Field(
        default="a", description="Prefix used for generating cluster group names (e.g., 'a' -> 'a0', 'a1')."
    )
    enabled_regions: list[str] = Field(
        default_factory=lambda: ["FSN", "HEL", "NBG"],
        description="List of enabled Hetzner regions to process (e.g., FSN, HEL, NBG).",
    )

    ignore_hosts_ips: list[str] = Field(
        default_factory=list,
        description="List of public IP addresses of servers to ignore during inventory generation.",
    )

    ignore_hosts_ids: list[str] = Field(
        default_factory=list,
        description="List of servers ids to ignore during inventory generation.",
    )

    no_privlink_hostnames: list[str] = Field(
        default_factory=list,
        description="List of generated hostnames that should not use the privlink IP, even if available for their DC.",
    )
    cluster_subnets: dict[str, SubnetDetail] = Field(
        default_factory=dict,
        description=(
            "Configuration for various cluster subnets, mapping a subnet key "
            "(e.g., 'vlan4001', 'fsn1dc18') to its details."
        ),
    )
    cloud_instance_names: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of Hetzner Cloud server IDs (as strings) to custom names for inventory.",
    )
    update_server_names_in_cloud: bool = Field(
        default=False,
        description="Whether to update server names in the Hetzner Cloud console to match generated names.",
    )
    update_server_labels_in_cloud: bool = Field(
        default=False,
        description="Whether to update server labels in the Hetzner Cloud console based on generated inventory.",
    )
    ssh_identity_file: str = Field(
        default="~/.ssh/id_rsa",
        description="Path to the SSH identity file to be used in the generated SSH config.",
    )
    vlan_id: str = Field(
        default="vlan4001",
        description=(
            "The VLAN ID (key in cluster_subnets) to use for IP allocation "
            "when a server is not using its DC-specific privlink IP."
        ),
    )
    domain_name: str = Field(
        default="mydom.dev",
        description="The domain name to use for constructing server hostnames.",
    )
    hostname_format: str = Field(
        default="{name}.{group}.{dc}.{domain_name}",
        description=(
            "Python f-string compatible format for generating server hostnames. "
            "Available placeholders: {name}, {group}, {dc}, {domain_name}."
        ),
    )


# Main configuration schema
class HetznerConfigSchema(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=f"{ENVPREFIX}_",
        env_nested_delimiter="_",
        case_sensitive=False,
        extra="allow",
    )
    name: str = Field(default="hetznerinv")
    hetzner_credentials: HetznerCredentials = Field(default_factory=HetznerCredentials)
    hetzner: HetznerInventoryConfig = Field(
        default_factory=HetznerInventoryConfig, description="Hetzner specific inventory generation settings."
    )


class Config(GenericConfig[HetznerConfigSchema]):
    _env_prefix = ENVPREFIX
    __config_class__ = HetznerConfigSchema

    @property
    def hetzner_credentials(self) -> HetznerCredentials:
        return self.conf.hetzner_credentials

    @property
    def hetzner(self) -> HetznerInventoryConfig:
        return self.conf.hetzner


def config(path: str | None = None, reload: bool = False) -> Config:
    GConfig[Config].set_conf_class(Config)
    if reload:
        GConfig[Config].reinit()
    GConfig[Config](path)
    return GConfig[Config].instance()
