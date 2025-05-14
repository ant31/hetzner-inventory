from pathlib import Path
from typing import Annotated

import typer
import yaml
from hetznerinv.hetzner.robot import Robot

from hetznerinv.config import config
from hetznerinv.generate_inventory import gen_cloud, gen_robot, ssh_config

cmd_generate_app = typer.Typer(
    help="Generate Hetzner inventory files and optionally an SSH configuration.",
    add_completion=False,
)


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

    robot_user = conf.hetzner_credentials.robot_user
    robot_password = conf.hetzner_credentials.robot_password

    if not robot_user or not robot_password:
        typer.secho(
            "Error: Hetzner Robot credentials (user, password) not found in configuration.",
            fg=typer.colors.RED,
            err=True,
        )
        if env == "production":  # Assuming robot is essential for production
            raise typer.Exit(code=1)
        else:
            typer.secho(
                "Warning: Robot credentials not found, Robot inventory will be skipped.",
                fg=typer.colors.YELLOW,
                err=True,
            )

    robot_client = None
    if robot_user and robot_password:
        robot_client = Robot(robot_user, robot_password)
    elif env == "production":  # If production and still no client, means creds were missing and we should have exited.
        # This is a safeguard, but previous check should catch it.
        typer.secho(
            "Error: Robot client could not be initialized for production due to missing credentials.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # Use the helper method to get the appropriate hcloud token
    token = conf.hetzner_credentials.get_hcloud_token(env)
    if not token:
        typer.secho(
            f"Error: Hetzner Cloud token for environment '{env}' not found in configuration. "
            "Please set HETZNER_HCLOUD_TOKEN or HETZNER_HCLOUD_TOKENS_{ENV} in your config/environment.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Generating inventory for environment: {env}")

    # Load existing inventory files if they exist, otherwise start fresh
    hosts_r_path = Path(f"inventory/{env}/hosts.yaml")
    hosts_c_path = Path(f"inventory/{env}/cloud.yaml")
    hosts_r = {}
    hosts_c = {}

    try:
        if hosts_r_path.exists():
            with open(hosts_r_path, encoding="utf-8") as f:
                inventory_robot = yaml.safe_load(f.read())
            if inventory_robot and "all" in inventory_robot and "hosts" in inventory_robot["all"]:
                hosts_r = inventory_robot["all"]["hosts"]
            else:
                typer.secho(
                    f"Warning: Robot inventory file {hosts_r_path} is empty or malformed.",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
    except (yaml.YAMLError, KeyError) as e:
        typer.secho(
            f"Warning: Could not load or parse {hosts_r_path}. Starting with empty robot inventory. Error: {e}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        hosts_r = {}  # Ensure it's reset on error

    try:
        if hosts_c_path.exists():
            with open(hosts_c_path, encoding="utf-8") as f:
                inventory_cloud = yaml.safe_load(f.read())
            if inventory_cloud and "all" in inventory_cloud and "hosts" in inventory_cloud["all"]:
                hosts_c = inventory_cloud["all"]["hosts"]
            else:
                typer.secho(
                    f"Warning: Cloud inventory file {hosts_c_path} is empty or malformed.",
                    fg=typer.colors.YELLOW,
                    err=True,
                )

    except (yaml.YAMLError, KeyError) as e:
        typer.secho(
            f"Warning: Could not load or parse {hosts_c_path}. Starting with empty cloud inventory. Error: {e}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        hosts_c = {}  # Ensure it's reset on error

    # Determine if any specific generation flags were set
    specific_generation_requested = generate_robot or generate_cloud or generate_ssh
    generate_all_parts = not specific_generation_requested

    # Robot inventory generation
    if generate_all_parts or generate_robot:
        if env == "production":
            if robot_client:
                typer.echo("Generating Robot inventory...")
                gen_robot(robot_client, conf.hetzner, hosts_r, env, process_all_hosts=process_all_hosts)
                typer.secho("Robot inventory generation complete.", fg=typer.colors.GREEN)
            else:
                typer.secho(
                    "Skipping Robot inventory generation: creds not configured or client failed for production.",
                    fg=typer.colors.YELLOW,
                )
        elif generate_robot:  # Explicit request for robot outside production
            typer.secho(
                "Skipping Robot inventory generation: Robot inventory is typically only for 'production' environment.",
                fg=typer.colors.YELLOW,
            )

    # Cloud inventory generation
    if generate_all_parts or generate_cloud:
        typer.echo("Generating Cloud inventory...")
        gen_cloud(hosts_c, token, conf.hetzner, env, process_all_hosts=process_all_hosts)
        typer.secho("Cloud inventory generation complete.", fg=typer.colors.GREEN)

    # SSH configuration generation
    should_generate_ssh_config = generate_all_parts or generate_ssh
    if should_generate_ssh_config:
        typer.echo("Generating SSH configuration...")
        ssh_config(env, conf.hetzner)
        typer.secho("SSH configuration generation complete.", fg=typer.colors.GREEN)
    elif specific_generation_requested and not generate_ssh:  # Specific flags used, but not --gen-ssh
        typer.echo("Skipping SSH configuration: --gen-ssh was not specified.")

    if not (generate_all_parts or generate_robot or generate_cloud or generate_ssh):
        typer.echo("No generation tasks were performed based on the flags provided.")

    typer.secho("Inventory generation process finished.", fg=typer.colors.BRIGHT_GREEN)
