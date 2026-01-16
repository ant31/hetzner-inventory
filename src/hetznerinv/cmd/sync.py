from pathlib import Path
from typing import Annotated

import typer
import yaml
from hcloud import Client
from rich.live import Live
from rich.table import Table

from hetznerinv.config import Config, config


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
    """Load existing inventory file or exit on failure"""
    if not path.exists():
        typer.secho(f"Error: {inv_type} inventory file {path} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        with open(path, encoding="utf-8") as f:
            inv = yaml.safe_load(f.read())
        if inv and "all" in inv and "hosts" in inv["all"] and inv["all"]["hosts"]:
            return inv["all"]["hosts"]
        typer.secho(
            f"Error: {inv_type} inventory file {path} is empty or malformed.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    except (yaml.YAMLError, KeyError) as e:
        typer.secho(
            f"Error: Could not load or parse {path}. Error: {e}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from e


cmd_sync_app = typer.Typer(
    help="Sync inventory data (names, labels) to Hetzner Cloud.",
    add_completion=False,
)


@cmd_sync_app.callback(invoke_without_command=True)
def sync_main(
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
            help="Environment to sync for (e.g., production, staging).",
        ),
    ] = "production",
    update_names: Annotated[
        bool,
        typer.Option(
            "--names",
            help="Sync server names from inventory to Hetzner Cloud.",
        ),
    ] = False,
    update_labels: Annotated[
        bool,
        typer.Option(
            "--labels",
            help="Sync server labels from inventory to Hetzner Cloud.",
        ),
    ] = False,
):
    """
    Syncs inventory data like server names and labels to Hetzner Cloud.
    """
    if ctx.invoked_subcommand is not None:
        return

    if not update_names and not update_labels:
        typer.secho("Error: At least one of --names or --labels must be specified.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    conf = config(path=str(config_path) if config_path else None)
    token = _get_cloud_token(conf, env)
    client = Client(token=token)

    typer.echo(f"Syncing inventory for environment: {env}")

    cloud_inventory_path = Path(f"inventory/{env}/cloud.yaml")
    hosts = _load_inv(cloud_inventory_path, "Cloud")

    servers_by_id = {s.id: s for s in client.servers.get_all()}

    table = Table(
        highlight=True,
        title="Hetzner Cloud Sync",
        title_justify="left",
        title_style="bold magenta",
    )
    table.add_column("ID", justify="left")
    table.add_column("Inventory Name", justify="left")
    table.add_column("Cloud Name", justify="left")
    table.add_column("Action", justify="left")
    table.add_column("Status", justify="left")

    live = Live(table, refresh_per_second=4)
    live.start()

    for host_name, host_data in hosts.items():
        server_id = host_data.get("server_info", {}).get("id")
        if not server_id:
            continue

        server = servers_by_id.get(server_id)
        if not server:
            live.console.print(
                f"[yellow]Warning: Server with ID {server_id} ({host_name}) not found in Hetzner Cloud. Skipping.[/yellow]"
            )
            continue

        actions = []
        status = "No changes"

        try:
            update_args = {}
            # Sync names
            if update_names:
                inventory_name = host_data.get("name")
                if inventory_name and server.name != inventory_name:
                    actions.append(f"Name: '{server.name}' -> '{inventory_name}'")
                    update_args["name"] = inventory_name

            # Sync labels
            if update_labels:
                inventory_labels = host_data.get("server_info", {}).get("labels", {})
                if server.labels != inventory_labels:
                    actions.append("Labels updated")
                    update_args["labels"] = inventory_labels

            if update_args:
                server.update(**update_args)
                status = "[green]Success[/green]"

        except Exception as e:
            status = f"[red]Error: {e}[/red]"

        table.add_row(
            str(server_id),
            host_name,
            server.name,
            ", ".join(actions) if actions else "None",
            status,
        )

    live.stop()

    typer.secho("Sync process finished.", fg=typer.colors.BRIGHT_GREEN)
