from pathlib import Path
from typing import Annotated

import typer
from hcloud import Client
from rich import print
from rich.table import Table

from hetznerinv.config import Config, HetznerInventoryConfig, config
from hetznerinv.generate_inventory import get_robot_servers_with_env
from hetznerinv.hetzner.robot import Robot


def _init_robot(conf: Config, env: str) -> Robot | None:
    """Init Robot client with creds validation"""
    robot_user, robot_password = conf.hetzner_credentials.get_robot_credentials(env)

    if not robot_user or not robot_password:
        typer.secho(
            f"Warning: Hetzner Robot credentials not found for environment '{env}'. Skipping Robot servers.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return None

    return Robot(robot_user, robot_password)


def _get_cloud_token(conf: Config, env: str) -> str | None:
    """Get and validate cloud token for env"""
    token = conf.hetzner_credentials.get_hcloud_token(env)
    if not token:
        typer.secho(
            f"Warning: Hetzner Cloud token not found for environment '{env}'. Skipping Cloud servers.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return None
    return token


def _get_all_envs(conf: Config) -> set[str]:
    """Get all configured environments from various sources"""
    envs = set()
    
    # From hetzner.envs
    envs.update(conf.hetzner.envs.keys())
    
    # From robot credentials
    envs.update(conf.hetzner_credentials.robot_credentials.keys())
    
    # From cloud tokens
    envs.update(conf.hetzner_credentials.hcloud_tokens.keys())
    
    # Always include production if we have default credentials
    if conf.hetzner_credentials.robot_user or conf.hetzner_credentials.hcloud_token:
        envs.add("production")
    
    return envs


def _get_robot_server_details(
    server,
    server_env: str,
    hetzner_config: HetznerInventoryConfig,
    vswitch_map: dict,
) -> dict:
    """Extract detailed information from a Robot server"""
    dc = server.datacenter.lower().replace("-", "")
    region = server.datacenter[0:3].upper()
    zone = server.datacenter[0:4].lower()
    
    # Get VLAN info
    vlan_id = vswitch_map.get(server.ip, {}).get("vlan", "N/A")
    
    # Try to determine private IP (this is approximate without full inventory generation)
    priv_ip = "N/A"
    vlan_ip = "N/A"
    
    # Check if DC has privlink configured
    dc_configured = dc in hetzner_config.cluster_subnets
    if dc_configured and hetzner_config.cluster_subnets[dc].privlink:
        priv_ip = hetzner_config.cluster_subnets[dc].start
    
    # VLAN IP from config
    if hetzner_config.vlan_id in hetzner_config.cluster_subnets:
        vlan_ip = hetzner_config.cluster_subnets[hetzner_config.vlan_id].start
    
    return {
        "id": str(server.number),
        "type": "Robot",
        "name": server.name or "N/A",
        "public_ip": server.ip,
        "priv_ip": priv_ip,
        "vlan_ip": vlan_ip,
        "product": server.product,
        "vlan_id": str(vlan_id),
        "region": region,
        "zone": zone,
        "dc": dc,
        "env": server_env,
        "extra": f"Status: {server.status}",
    }


def _get_cloud_server_details(
    server,
    env: str,
    hetzner_config: HetznerInventoryConfig,
) -> dict:
    """Extract detailed information from a Cloud server"""
    region = server.datacenter.name[0:3].upper()
    zone = server.datacenter.location.name.lower()
    dc = server.datacenter.name.lower().replace("-", "")
    
    priv_ip = server.private_net[0].ip if server.private_net else "N/A"
    public_ip = server.public_net.ipv4.ip if server.public_net.ipv4 else "N/A"
    
    labels_str = ", ".join([f"{k}={v}" for k, v in server.labels.items()]) if server.labels else "None"
    
    return {
        "id": str(server.id),
        "type": "Cloud",
        "name": server.name,
        "public_ip": public_ip,
        "priv_ip": priv_ip,
        "vlan_ip": priv_ip,  # For cloud, private IP is the VLAN IP
        "product": server.server_type.name,
        "vlan_id": hetzner_config.vlan_id,
        "region": region,
        "zone": zone,
        "dc": dc,
        "env": env,
        "extra": labels_str,
    }


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
        str | None,
        typer.Option(
            "--env",
            help="Environment to list servers for. If not specified, lists all configured environments.",
        ),
    ] = None,
):
    """
    Lists servers from Hetzner Robot and Cloud with comprehensive details.
    Shows one table per environment with all available information.
    """
    if ctx.invoked_subcommand is not None:
        return

    conf = config(path=str(config_path) if config_path else None)
    
    # Determine which environments to list
    if env:
        environments = [env]
    else:
        environments = sorted(_get_all_envs(conf))
        if not environments:
            typer.secho("No environments configured.", fg=typer.colors.YELLOW)
            return
    
    for current_env in environments:
        hetzner_conf = conf.hetzner_for_env(current_env)
        all_servers = []
        
        # Collect Robot servers
        robot_client = _init_robot(conf, current_env)
        if robot_client:
            # Get vswitch mapping
            vswitches = robot_client.vswitch.list()
            vswitch_map = {}
            for vswitch in vswitches.values():
                for s in vswitch.server:
                    vswitch_map[s["server_ip"]] = {"vlan": vswitch.vlan, "id": vswitch.id}
            
            all_servers_with_env = get_robot_servers_with_env(
                robot_client, hetzner_conf, process_all_hosts=True
            )
            
            for _server_number, (server, server_env) in all_servers_with_env.items():
                if server_env == current_env:
                    details = _get_robot_server_details(server, server_env, hetzner_conf, vswitch_map)
                    all_servers.append(details)
        
        # Collect Cloud servers
        token = _get_cloud_token(conf, current_env)
        if token:
            client = Client(token=token)
            hcloud_servers = client.servers.get_all()
            
            for server in hcloud_servers:
                details = _get_cloud_server_details(server, current_env, hetzner_conf)
                all_servers.append(details)
        
        # Display combined table if we have any servers
        if all_servers:
            table = Table(
                title=f"Hetzner Servers - Environment: {current_env}",
                highlight=True,
                title_justify="left",
                title_style="bold magenta",
                row_styles=["bold", "none"],
            )
            table.add_column("#", justify="right")
            table.add_column("Type", justify="left")
            table.add_column("ID", justify="left")
            table.add_column("Name", justify="left")
            table.add_column("Product", justify="left")
            table.add_column("Public IP", justify="left")
            table.add_column("Priv IP", justify="left")
            table.add_column("VLAN IP", justify="left")
            table.add_column("VLAN ID", justify="left")
            table.add_column("Zone", justify="left")
            table.add_column("Extra", justify="left")
            
            # Sort by type (Cloud first, then Robot) and then by ID
            all_servers.sort(key=lambda s: (s["type"], int(s["id"])))
            
            for i, srv in enumerate(all_servers, 1):
                table.add_row(
                    str(i),
                    f"[cyan]{srv['type']}[/cyan]" if srv["type"] == "Cloud" else f"[yellow]{srv['type']}[/yellow]",
                    srv["id"],
                    srv["name"],
                    srv["product"],
                    f"[pale_turquoise1]{srv['public_ip']}[/pale_turquoise1]",
                    srv["priv_ip"],
                    f"[sky_blue1]{srv['vlan_ip']}[/sky_blue1]",
                    srv["vlan_id"],
                    f"[sea_green1]{srv['region']}[/sea_green1] {srv['dc']}",
                    f"[dim]{srv['extra']}[/dim]",
                )
            
            print(table)
            print()  # Add spacing between environment tables
        else:
            typer.secho(f"No servers found for environment: {current_env}", fg=typer.colors.YELLOW)
            print()
