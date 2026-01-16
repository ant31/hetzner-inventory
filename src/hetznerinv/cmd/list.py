from pathlib import Path
from typing import Annotated

import typer
from hcloud import Client
from rich import print
from rich.table import Table

from hetznerinv.config import Config, config
from hetznerinv.generate_inventory import get_robot_servers_with_env
from hetznerinv.hetzner.robot import Robot


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


cmd_list_app = typer.Typer(
    help="List servers from Hetzner Robot and Cloud.",
    add_completion=False,
)


@cmd_list_app.callback(invoke_without_command=True)
def list_main(
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
            help="Environment to list servers for (e.g., production, staging).",
        ),
    ] = "production",
):
    """
    Lists servers from Hetzner Robot and Cloud for a specified environment.
    """
    if ctx.invoked_subcommand is not None:
        return

    conf = config(path=str(config_path) if config_path else None)
    typer.echo(f"Listing servers for environment: {env}")

    # Robot Servers
    robot_client = _init_robot(conf, env)
    if robot_client:
        hetzner_conf = conf.hetzner
        all_servers_with_env = get_robot_servers_with_env(robot_client, hetzner_conf, process_all_hosts=True)

        table = Table(
            title="Hetzner Robot Servers",
            highlight=True,
            title_justify="left",
            title_style="bold magenta",
            row_styles=["bold", "none"],
        )
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Public IP")
        table.add_column("Product")
        table.add_column("Assigned Env")
        for server_number, (server, server_env) in sorted(all_servers_with_env.items()):
            table.add_row(
                str(server_number),
                server.name,
                f"[pale_turquoise1]{server.ip}",
                server.product,
                f"[sea_green1]{server_env}",
            )
        print(table)

    # Cloud Servers
    token = _get_cloud_token(conf, env)
    client = Client(token=token)
    hcloud_servers = client.servers.get_all()

    if hcloud_servers:
        table = Table(
            title=f"Hetzner Cloud Servers ({env})",
            highlight=True,
            title_justify="left",
            title_style="bold magenta",
            row_styles=["bold", "none"],
        )
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Public IP")
        table.add_column("Type")
        table.add_column("Labels")
        for server in sorted(hcloud_servers, key=lambda s: s.id):
            labels_str = ", ".join([f"{k}={v}" for k, v in server.labels.items()])
            table.add_row(
                str(server.id),
                server.name,
                f"[pale_turquoise1]{server.public_net.ipv4.ip}",
                server.server_type.name,
                f"[sky_blue1]{labels_str}",
            )
        print(table)
