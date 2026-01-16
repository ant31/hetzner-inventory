# pylint: disable=no-self-argument
import logging
from typing import Any

from ant31box.config import LOGGING_CONFIG as LG
from ant31box.config import BaseConfig, GConfig, GenericConfig, LoggingConfigSchema
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOGGING_CONFIG: dict[str, Any] = LG
LOGGING_CONFIG["loggers"].update({"root": {"handlers": ["default"], "level": "DEBUG", "propagate": True}})

logger: logging.Logger = logging.getLogger("hetznerinv")


class LoggingCustomConfigSchema(LoggingConfigSchema):
    log_config: dict[str, Any] | str | None = Field(default_factory=lambda: LOGGING_CONFIG)


ENVPREFIX = "HETZNER"

# New sub-models for structured configuration


class RobotCredentials(BaseConfig):
    """Hetzner Robot user and password."""

    user: str = Field(..., description="Hetzner Robot username.")
    password: str = Field(..., description="Hetzner Robot password.")


class HetznerCredentials(BaseConfig):
    """
    Hetzner Robot credentials
    """

    #     model_config = SettingsConfigDict(env_prefix='HETZNER_'')
    # Hetzner Robot credentials
    robot_user: str = Field(default="", description="Default Hetzner Robot username if not specified per environment.")
    robot_password: str = Field(
        default="", description="Default Hetzner Robot password if not specified per environment."
    )

    robot_credentials: dict[str, RobotCredentials] = Field(
        default_factory=dict,
        description=(
            "Hetzner Robot credentials, keyed by environment name (e.g., 'staging': "
            "{'user': '...', 'password': '...'})."
        ),
    )

    hcloud_token: str = Field(default="", description="Default Hetzner Cloud token if not specified per environment.")
    # Hetzner Cloud token
    hcloud_tokens: dict[str, str] = Field(
        default_factory=dict,
        description="Hetzner Cloud tokens, keyed by environment name (e.g., 'production': 'token').",
    )

    def get_robot_credentials(self, env: str) -> tuple[str, str]:
        """
        Retrieves the Hetzner Robot credentials for the specified environment.

        It first checks for environment-specific credentials.
        If not found, it falls back to the general `robot_user` and `robot_password`.
        Returns a tuple of (user, password).
        """
        if env in self.robot_credentials:
            creds = self.robot_credentials[env]
            return creds.user, creds.password
        return self.robot_user, self.robot_password

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


class RobotEnvAssignment(BaseConfig):
    """Configuration for assigning Robot servers to environments."""

    default: str = Field(default="production", description="Default environment for servers not otherwise matched.")
    by_vswitch: dict[str, str] = Field(
        default_factory=dict, description="Assign environment by vswitch ID (e.g. {'1234': 'staging'})."
    )
    by_server_id: dict[str, str] = Field(
        default_factory=dict, description="Assign environment by server ID (e.g. {'1234567': 'staging'})."
    )
    by_server_name_regex: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Assign environment by server name regex (e.g. {'^staging-': 'staging'}). Processed in definition order."
        ),
    )

    @field_validator("by_vswitch", "by_server_id", mode="before")
    @classmethod
    def _coerce_dict_keys_to_str(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return {str(key): value for key, value in v.items()}
        return v


class EnvSettings(BaseConfig):
    """Environment-specific settings that override defaults."""

    vlan_id: str | None = Field(default=None, description="Environment-specific VLAN ID.")
    ssh_user: str | None = Field(default=None, description="Environment-specific SSH user.")


class HetznerInventoryConfig(BaseConfig):
    """Configuration specific to Hetzner inventory generation."""

    robot_env_assignment: RobotEnvAssignment = Field(
        default_factory=RobotEnvAssignment, description="Rules for assigning Robot servers to environments."
    )
    envs: dict[str, EnvSettings] = Field(
        default_factory=dict,
        description="Environment-specific settings overrides, keyed by environment name.",
    )
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
    ssh_user: str = Field(default="kadmin", description="Default SSH user for all servers.")
    ssh_user_per_server_id: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of server ID to a specific SSH user, overriding environment and default settings.",
    )
    vlan_id: str = Field(
        default="vlan4001",
        description=(
            "The VLAN ID (key in cluster_subnets) to use for IP allocation "
            "when a server is not using its DC-specific privlink IP. Can be overridden per environment."
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

    @field_validator(
        "product_options", "cluster_subnets", "cloud_instance_names", "envs", "ssh_user_per_server_id", mode="before"
    )
    @classmethod
    def _coerce_dict_keys_to_str(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return {str(key): value for key, value in v.items()}
        return v


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

    def hetzner_for_env(self, env: str) -> HetznerInventoryConfig:
        """
        Returns a new config object with environment-specific overrides applied.
        """
        hetzner_config = self.hetzner.model_copy(deep=True)
        if env in hetzner_config.envs:
            env_settings = hetzner_config.envs[env]
            if env_settings.vlan_id is not None:
                hetzner_config.vlan_id = env_settings.vlan_id
            if env_settings.ssh_user is not None:
                hetzner_config.ssh_user = env_settings.ssh_user
        return hetzner_config


def config(path: str | None = None, reload: bool = False) -> Config:
    GConfig[Config].set_conf_class(Config)
    if reload:
        GConfig[Config].reinit()
    GConfig[Config](path)
    return GConfig[Config].instance()
