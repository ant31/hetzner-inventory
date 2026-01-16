from pathlib import Path
from typing import Annotated, Any

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


def _sync_server(server: Any, host_data: dict, update_names: bool, update_labels: bool, dry_run: bool) -> dict:
    """Processes a single server for synchronization and returns row data for the table."""
    name_before = server.name
    labels_before = server.labels

    name_after = name_before
    labels_after = labels_before

    changes = []
    update_args = {}
    if update_names:
        inventory_name = host_data.get("name")
        if inventory_name and server.name != inventory_name:
            changes.append("Name")
            name_after = inventory_name
            update_args["name"] = inventory_name

    if update_labels:
        inventory_labels = host_data.get("server_info", {}).get("labels", {})
        if server.labels != inventory_labels:
            changes.append("Labels")
            labels_after = inventory_labels
            update_args["labels"] = inventory_labels

    status = "No changes"
    if update_args:
        if dry_run:
            status = "[yellow]Dry Run[/yellow]"
        else:
            try:
                server.update(**update_args)
                status = "[green]Success[/green]"
            except Exception as e:
                status = f"[red]Error: {e}[/red]"
                name_after = name_before
                labels_after = labels_before

    labels_before_str = ", ".join([f"{k}={v}" for k, v in labels_before.items()])
    labels_after_str = ", ".join([f"{k}={v}" for k, v in labels_after.items()])

    return {
        "name_before": name_before,
        "name_after": name_after,
        "labels_before_str": labels_before_str,
        "labels_after_str": labels_after_str,
        "changes_str": ", ".join(changes) if changes else "None",
        "status": status,
    }


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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Perform a dry run without making any changes to Hetzner Cloud.",
        ),
    ] = False,
):
    """
    Syncs inventory data like server names and labels to Hetzner Cloud.
    """
    if ctx.invoked_subcommand is not None:
        return

    if dry_run:
        typer.secho("Performing a dry run. No changes will be applied.", fg=typer.colors.YELLOW)

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
    table.add_column("Cloud Name (Before)", justify="left")
    table.add_column("Cloud Name (After)", justify="left")
    table.add_column("Labels (Before)", justify="left")
    table.add_column("Labels (After)", justify="left")
    table.add_column("Changes", justify="left")
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
                f"[yellow]Warning: Server with ID {server_id} ({host_name}) not found in Hetzner Cloud. "
                "Skipping.[/yellow]"
            )
            continue

        row_data = _sync_server(server, host_data, update_names, update_labels, dry_run)

        table.add_row(
            str(server_id),
            host_name,
            row_data["name_before"],
            row_data["name_after"],
            row_data["labels_before_str"],
            row_data["labels_after_str"],
            row_data["changes_str"],
            row_data["status"],
        )

    live.stop()

    if dry_run:
        typer.secho("Dry run finished. No changes were made.", fg=typer.colors.BRIGHT_GREEN)
    else:
        typer.secho("Sync process finished.", fg=typer.colors.BRIGHT_GREEN)
