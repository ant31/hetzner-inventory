from pathlib import Path
from typing import Annotated

import typer
import yaml

from hetznerinv.config import Config, HetznerInventoryConfig, config
from hetznerinv.generate_inventory import gen_cloud, gen_robot, ssh_config
from hetznerinv.hetzner.robot import Robot

cmd_generate_app = typer.Typer(
    help="Generate Hetzner inventory files and optionally an SSH configuration.",
    add_completion=False,
)


def _init_robot(conf: Config, env: str) -> Robot | None:
    """Init Robot client with creds validation"""
    robot_user, robot_password = conf.hetzner_credentials.get_robot_credentials(env)

    if not robot_user or not robot_password:
        typer.secho(
            f"Error: Hetzner Robot credentials (user, password) not found for environment '{env}' in configuration.",
            fg=typer.colors.RED,
            err=True,
        )
        if env == "production":
            raise typer.Exit(code=1)
        typer.secho(
            "Warning: Robot credentials not found, Robot inventory will be skipped.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return None

    return Robot(robot_user, robot_password)


def _get_cloud_token(conf: Config, env: str) -> str:
    """Get and validate cloud token for env"""
    token = conf.hetzner_credentials.get_hcloud_token(env)
    if not token:
        typer.secho(
            f"Error: Hetzner Cloud token for environment '{env}' not found in configuration. "
            "Please set HETZNER_HCLOUD_TOKEN or HETZNER_HCLOUD_TOKENS_{ENV} in your config/environment.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    return token


def _load_inv(path: Path, inv_type: str) -> dict:
    """Load existing inventory file or return empty dict"""
    if not path.exists():
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            inv = yaml.safe_load(f.read())
        if inv and "all" in inv and "hosts" in inv["all"]:
            return inv["all"]["hosts"]
        typer.secho(
            f"Warning: {inv_type} inventory file {path} is empty or malformed.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return {}
    except (yaml.YAMLError, KeyError) as e:
        typer.secho(
            f"Warning: Could not load or parse {path}. Starting with empty {inv_type} inventory. Error: {e}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return {}


def _gen_robot_inv(
    robot_client: Robot | None,
    conf: HetznerInventoryConfig,
    hosts: dict,
    env: str,
    process_all: bool,
    requested: bool,
    verbose: bool,
) -> None:
    """Generate Robot inventory if applicable"""
    if robot_client:
        typer.echo("Generating Robot inventory...")
        gen_robot(robot_client, conf, hosts, env, process_all_hosts=process_all, verbose=verbose)
        typer.secho("Robot inventory generation complete.", fg=typer.colors.GREEN)
    elif requested:
        # This case is when --gen-robot is specified for an env without credentials.
        # _init_robot already prints a warning. This adds context.
        typer.secho(
            "Skipping Robot inventory generation: Robot credentials not configured for this environment.",
            fg=typer.colors.YELLOW,
        )


def _gen_cloud_inv(
    hosts: dict,
    token: str,
    conf: HetznerInventoryConfig,
    env: str,
    process_all: bool,
) -> None:
    """Generate Cloud inventory"""
    typer.echo("Generating Cloud inventory...")
    gen_cloud(hosts, token, conf, env, process_all_hosts=process_all)
    typer.secho("Cloud inventory generation complete.", fg=typer.colors.GREEN)


def _gen_ssh_cfg(env: str, conf: HetznerInventoryConfig) -> None:
    """Generate SSH configuration"""
    typer.echo("Generating SSH configuration...")
    ssh_config(env, conf)
    typer.secho("SSH configuration generation complete.", fg=typer.colors.GREEN)


@cmd_generate_app.callback(invoke_without_command=True)
def generate_main(
    ctx: typer.Context,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to a custom YAML configuration file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    env: Annotated[
        str,
        typer.Option(
            "--env",
            help="Environment to generate inventory for (e.g., production, staging).",
        ),
    ] = "production",
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show all servers found and their assigned environments before filtering.",
        ),
    ] = False,
    generate_robot: Annotated[
        bool,
        typer.Option(
            "--gen-robot",
            help="Generate Robot inventory. If specified, only selected --gen-* parts are generated.",
        ),
    ] = False,
    generate_cloud: Annotated[
        bool,
        typer.Option(
            "--gen-cloud",
            help="Generate Cloud inventory. If specified, only selected --gen-* parts are generated.",
        ),
    ] = False,
    generate_ssh: Annotated[
        bool,
        typer.Option(
            "--gen-ssh",
            help="Generate SSH configuration. If specified, only selected --gen-* parts are generated.",
        ),
    ] = False,
    process_all_hosts: Annotated[
        bool,
        typer.Option(
            "--all-hosts",
            help="Process all hosts and disregard ignore_hosts_ips and ignore_hosts_ids from config.",
        ),
    ] = False,
):
    """
    Generates inventory files for Hetzner Robot and Cloud servers.
    Optionally creates an SSH configuration file.
    """
    if ctx.invoked_subcommand is not None:
        return

    conf = config(path=str(config_path) if config_path else None)
    hetzner_conf = conf.hetzner_for_env(env)

    robot_client = _init_robot(conf, env)
    token = _get_cloud_token(conf, env)

    typer.echo(f"Generating inventory for environment: {env}")

    # Load existing inventory files
    hosts_r = _load_inv(Path(f"inventory/{env}/hosts.yaml"), "Robot")
    hosts_c = _load_inv(Path(f"inventory/{env}/cloud.yaml"), "Cloud")

    # Determine generation scope
    specific_gen = generate_robot or generate_cloud or generate_ssh
    gen_all = not specific_gen

    # Generate inventories
    if gen_all or generate_robot:
        _gen_robot_inv(robot_client, hetzner_conf, hosts_r, env, process_all_hosts, generate_robot, verbose)

    if gen_all or generate_cloud:
        _gen_cloud_inv(hosts_c, token, hetzner_conf, env, process_all_hosts)

    # Generate SSH config
    if gen_all or generate_ssh:
        _gen_ssh_cfg(env, hetzner_conf)
    elif specific_gen:
        typer.echo("Skipping SSH configuration: --gen-ssh was not specified.")

    if not (gen_all or generate_robot or generate_cloud or generate_ssh):
        typer.echo("No generation tasks were performed based on the flags provided.")

    typer.secho("Inventory generation process finished.", fg=typer.colors.BRIGHT_GREEN)
