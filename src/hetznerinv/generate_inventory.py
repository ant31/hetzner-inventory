import re
from ipaddress import IPv4Address

import yaml
from hcloud import Client
from rich import print
from rich.live import Live
from rich.table import Table

from hetznerinv.config import HetznerInventoryConfig
from hetznerinv.hetzner.robot import Robot


def hosts_by_id(hosts: list) -> dict:
    hid = {}
    for h in hosts:
        hid[h["server_info"]["id"]] = h
    return hid


def _get_ssh_user(server_id: str | int, hetzner_config: HetznerInventoryConfig) -> str:
    """Get SSH user for a server, checking per-server overrides first, then the default."""
    server_id_str = str(server_id)
    if server_id_str in hetzner_config.ssh_user_per_server_id:
        return hetzner_config.ssh_user_per_server_id[server_id_str]
    return hetzner_config.ssh_user


def get_robot_servers_with_env(robot: Robot, hetzner_config: HetznerInventoryConfig, process_all_hosts: bool) -> dict:
    """Get all servers with their assigned environment."""
    servers_with_env = {}

    # Build a map of server IP to vswitch ID for environment assignment
    vswitches = robot.vswitch.list()
    server_ip_to_vswitch_id = {}
    for vswitch in vswitches.values():
        for s in vswitch.server:
            server_ip_to_vswitch_id[s["server_ip"]] = vswitch.id

    assignment_rules = hetzner_config.robot_env_assignment

    for server in robot.servers:
        if server.ip is None:
            continue

        if not process_all_hosts:
            if server.ip in hetzner_config.ignore_hosts_ips:
                continue
            if str(server.number) in hetzner_config.ignore_hosts_ids:
                continue

        # Determine server environment by applying rules in order of increasing precedence.
        # Default -> vSwitch -> Server Name Regex -> Server ID
        server_env = assignment_rules.default

        # by vswitch
        vswitch_id = server_ip_to_vswitch_id.get(server.ip)
        if vswitch_id and str(vswitch_id) in assignment_rules.by_vswitch:
            server_env = assignment_rules.by_vswitch[str(vswitch_id)]

        # by server name regex
        if server.name:
            for regex, env_val in assignment_rules.by_server_name_regex.items():
                if re.search(regex, server.name):
                    server_env = env_val
                    break

        # by server ID (highest precedence)
        if str(server.number) in assignment_rules.by_server_id:
            server_env = assignment_rules.by_server_id[str(server.number)]

        servers_with_env[server.number] = (server, server_env)
    return servers_with_env


def _get_server_name(server, hids: dict, product: str, options: str) -> str:
    """Get server name from existing hosts or generate new one"""
    if server.number in hids:
        return hids[server.number]["name"]
    return f"{server.number}-{product}{options}"


def _get_product_info(server, hetzner_config: HetznerInventoryConfig) -> tuple[str, str]:
    """Extract and normalize product info and options"""
    product = server.product.lower().replace("-", "").replace(" ", "")
    if product == "serverauction":
        product = ""
    if product.startswith("dellpoweredge\u2122r6515"):
        product = product.split("dellpoweredge\u2122r6515")[1]
    if product.startswith("dellpoweredge\u2122r6615"):
        product = product.split("dellpoweredge\u2122r6615")[1]

    options = ""
    if str(server.number) in hetzner_config.product_options:
        options = hetzner_config.product_options[str(server.number)]
    elif product in hetzner_config.product_options:
        options = hetzner_config.product_options[product]

    return product, options


def _get_ip_addresses(
    server,
    name: str,
    dc: str,
    vlan_id: int,
    hetzner_config: HetznerInventoryConfig,
    hosts_init: dict,
    privips: dict,
    vlanips: dict,
    force: bool,
) -> tuple[str, str]:
    """Determine private and VLAN IP addresses for server"""
    last_ipvlan = hetzner_config.cluster_subnets[vlan_id].start
    dc_configured = dc in hetzner_config.cluster_subnets

    if (
        dc_configured
        and hetzner_config.cluster_subnets[dc].privlink
        and name not in hetzner_config.no_privlink_hostnames
    ):
        priv_ip = hetzner_config.cluster_subnets[dc].start
    else:
        priv_ip = last_ipvlan

    if name in hosts_init and not force:
        if "ip" in hosts_init[name] and hosts_init[name]["ip"]:
            priv_ip = hosts_init[name]["ip"]
        if "ip_vlan" in hosts_init[name] and hosts_init[name]["ip_vlan"]:
            last_ipvlan = hosts_init[name]["ip_vlan"]

    privips[priv_ip] = True
    vlanips[last_ipvlan] = True

    # Update subnet starts
    if dc_configured:
        last_privip = hetzner_config.cluster_subnets[dc].start
        hetzner_config.cluster_subnets[dc].start = str(IPv4Address(last_privip) + 1)
        while hetzner_config.cluster_subnets[dc].start in privips:
            hetzner_config.cluster_subnets[dc].start = str(
                IPv4Address(hetzner_config.cluster_subnets[dc].start) + 1
            )

    hetzner_config.cluster_subnets[vlan_id].start = str(IPv4Address(last_ipvlan) + 1)

    while hetzner_config.cluster_subnets[vlan_id].start in vlanips:
        current_ip = hetzner_config.cluster_subnets[vlan_id].start
        hetzner_config.cluster_subnets[vlan_id].start = str(IPv4Address(current_ip) + 1)

    return priv_ip, last_ipvlan


def _create_host_entry(
    server,
    name: str,
    priv_ip: str,
    vlan_ip: str,
    product: str,
    options: str,
    hetzner_config: HetznerInventoryConfig,
) -> dict:
    """Create host dictionary entry"""
    region = server.datacenter[0:3].lower()
    zone = server.datacenter[0:4].lower()
    dc = server.datacenter.lower().replace("-", "")
    group = f"{hetzner_config.cluster_prefix}{server.number % 4}"

    hostname = hetzner_config.hostname_format.format(
        name=name, group=group, dc=dc, domain_name=hetzner_config.domain_name
    )
    ssh_user = _get_ssh_user(server.number, hetzner_config)

    return {
        "name": name,
        "ip": priv_ip,
        "ip_vlan": vlan_ip,
        "ansible_ssh_host": server.ip,
        "ansible_user": ssh_user,
        "hostname": hostname,
        "model": product + options,
        "protected": (server.name not in ["", "toReset"] and server.name is not None),
        "region": region,
        "zone": zone,
        "server_info": {
            "dc": dc,
            "id": server.number,
            "group": group,
            "hetzner": {
                "options": options,
                "public_ip": server.ip,
                "current_name": server.name,
                "product": server.product,
                "datacenter": server.datacenter,
            },
        },
    }


def list_all_hosts(
    robot: Robot,
    hetzner_config: HetznerInventoryConfig,
    hosts_init=None,
    force=False,
    process_all_hosts: bool = False,
    env: str = "production",
    verbose: bool = False,
):
    if hosts_init is None:
        hosts_init = {}

    vlan_id = hetzner_config.vlan_id
    hosts = {}
    hids = hosts_by_id(list(hosts_init.values()))
    privips = {}
    vlanips = {}

    all_servers_with_env = get_robot_servers_with_env(robot, hetzner_config, process_all_hosts)

    if verbose:
        verbose_table = Table(
            highlight=True,
            title="All Hetzner Robot servers found (before filtering)",
            title_justify="left",
            title_style="bold magenta",
        )
        verbose_table.add_column("ID", justify="left")
        verbose_table.add_column("Name", justify="left")
        verbose_table.add_column("Public IP", justify="left")
        verbose_table.add_column("Product", justify="left")
        verbose_table.add_column("Assigned Env", justify="left")
        for server_number, (server, server_env) in sorted(all_servers_with_env.items()):
            verbose_table.add_row(str(server_number), server.name, server.ip, server.product, server_env)
        print(verbose_table)

    servers = {num: s for num, (s, s_env) in all_servers_with_env.items() if s_env == env}

    table = Table(
        highlight=True,
        title="Hetzner Robot servers",
        title_justify="left",
        title_style="bold magenta",
        row_styles=["bold", "none"],
    )
    table.add_column("#", justify="left")
    table.add_column("ID", justify="left")
    table.add_column("Name", justify="left")
    table.add_column("Product", justify="left")
    table.add_column("Public IP", justify="left")
    table.add_column("Priv IP", justify="left")
    table.add_column("Vlan IP", justify="left")
    table.add_column("Zone", justify="left")
    live = Live(table, refresh_per_second=4)
    live.start()

    for i, number in enumerate(sorted(servers.keys())):
        server = servers[number]
        dc = server.datacenter.lower().replace("-", "")
        region = server.datacenter[0:3].lower()

        # Validate datacenter config
        if vlan_id not in hetzner_config.cluster_subnets:
            live.console.print(
                f"Warning: VLAN ID '{vlan_id}' not in cluster_subnets config. Skipping server {server.number}."
            )
            continue

        product, options = _get_product_info(server, hetzner_config)
        name = _get_server_name(server, hids, product, options)
        priv_ip, vlan_ip = _get_ip_addresses(
            server, name, dc, vlan_id, hetzner_config, hosts_init, privips, vlanips, force
        )

        host = _create_host_entry(server, name, priv_ip, vlan_ip, product, options, hetzner_config)
        hosts[name] = host

        table.add_row(
            str(i + 1),
            str(server.number),
            name,
            server.product,
            f"[pale_turquoise1]{server.ip}",
            priv_ip,
            f"[sky_blue1]{vlan_ip}",
            f"[sea_green1]{region.upper()}[default] {dc}",
        )
    live.stop()
    return hosts


def ansible_hosts(hosts, hetzner_group):
    inventory = {"all": {"hosts": {}}}
    ordered_keys = sorted(hosts.keys())
    for k in ordered_keys:
        host = hosts[k]
        inventory["all"]["hosts"][k] = host

    if "children" not in inventory["all"]:
        inventory["all"]["children"] = {}

    groups = inventory["all"]["children"]
    dcs = {}
    models = {}
    for h in ordered_keys:
        v = hosts[h]
        group = "group_" + v["server_info"]["group"]
        dc = "datacenter_" + v["server_info"]["dc"]
        model = "model_" + v["model"]
        dcs[dc] = {}
        models[model] = {}
        if group not in groups:
            groups[group] = {"hosts": {}}
        if model not in groups:
            groups[model] = {"hosts": {}}
        if dc not in groups:
            groups[dc] = {"hosts": {}}
        groups[dc]["hosts"][h] = {}
        groups[model]["hosts"][h] = {}
        groups[group]["hosts"][h] = {}

    inventory["all"]["children"] = groups
    inventory["all"]["children"][hetzner_group] = {"children": models}
    inventory["all"]["children"]["hetzner"] = {"children": {"hetzner_robot": {}, "hetzner_cloud": {}}}
    return inventory


def _ssh_config(servers: dict, hetzner_config: HetznerInventoryConfig, name: str = ""):
    conf = []
    table = Table(
        highlight=True,
        title=f"SSH Config: {name}",
        title_justify="left",
        title_style="bold magenta",
        row_styles=["bold", "none"],
    )

    table.add_column("#", justify="right")
    table.add_column("Name", justify="left")
    table.add_column("Host", justify="left")
    table.add_column("IP", justify="left")
    table.add_column("User", justify="left")
    table.add_column("Id", justify="left")
    with Live(table, refresh_per_second=4):
        row_num = 0
        for k, s in servers.items():
            names = [s["name"]]
            if k != s["name"]:
                names.append(k)
            for hostname_alias in names:
                row_num += 1
                table.add_row(
                    str(row_num),
                    hostname_alias,
                    s["hostname"],
                    s["ansible_ssh_host"],
                    s["ansible_user"],
                    hetzner_config.ssh_identity_file,
                )
                template = f"""
#{s["hostname"]}
Host {hostname_alias}
    HostName {s["ansible_ssh_host"]}
    User {s["ansible_user"]}
    IdentityFile {hetzner_config.ssh_identity_file}
"""
                conf.append(template)
    return conf


def gen_robot(
    robot: Robot,
    hetzner_config: HetznerInventoryConfig,
    hosts_inv=None,
    env="production",
    process_all_hosts: bool = False,
    verbose: bool = False,
):
    if hosts_inv is None:
        hosts_inv = {}
    hosts = list_all_hosts(
        robot, hetzner_config, hosts_inv, process_all_hosts=process_all_hosts, env=env, verbose=verbose
    )
    inventory = ansible_hosts(hosts, "hetzner_robot")
    with open(f"inventory/{env}/hosts.yaml", "w") as f:
        f.write(yaml.dump(inventory))


def prep_k8s():
    # This function still reads a fixed path. Consider making it configurable if needed.
    try:
        with open("inventory/02-k8s-a1.yaml") as f:
            inventory_a = yaml.safe_load(f.read())
    except FileNotFoundError:
        print("Warning: inventory/02-k8s-a1.yaml not found. k8s groups will be empty.")
        return {}
    except yaml.YAMLError as e:
        print(f"Warning: Error parsing inventory/02-k8s-a1.yaml: {e}. k8s groups will be empty.")
        return {}

    nodes = {}
    groups = ["etcd", "kube_node", "kube_control_plane"]
    inventories = [inventory_a]  # inventory_a could be None if file not found/parsed
    if not inventory_a:  # Check if inventory_a is None or empty
        return nodes

    for g in groups:
        for inv in inventories:
            if inv and "all" in inv and "children" in inv["all"] and g in inv["all"]["children"]:
                for h in inv["all"]["children"][g]["hosts"]:
                    if h not in nodes:
                        nodes[h] = {}
                    nodes[h][g] = "yes"
            else:
                print(f"no {g} in inventory structure or inventory is empty/invalid")
    return nodes


def _filter_cloud_servers(hcloud_servers, hetzner_config: HetznerInventoryConfig, process_all_hosts: bool) -> dict:
    """Filter cloud servers based on ignore lists"""
    servers = {}
    for s in hcloud_servers:
        if s.public_net.ipv4.ip is None:
            continue
        if not process_all_hosts:
            if s.public_net.ipv4.ip in hetzner_config.ignore_hosts_ips:
                continue
            if str(s.id) in hetzner_config.ignore_hosts_ids:
                continue
        servers[s.id] = s
    return servers


def _get_cloud_server_name(
    server, hids: dict, product: str, hetzner_config: HetznerInventoryConfig, force: bool
) -> str:
    """Determine cloud server name from config or existing hosts"""
    name = hetzner_config.cloud_instance_names.get(str(server.id), f"{server.id}-{product}")
    if server.id in hids and not force:
        name = hids[server.id]["name"]
    return name


def _prep_cloud_labels(
    server,
    group: str,
    name: str,
    k8s_groups: dict,
    hetzner_config: HetznerInventoryConfig,
) -> dict:
    """Prepare labels for cloud server"""
    generated_labels = {"group": group}

    if server.placement_group:
        generated_labels.update(server.placement_group.labels)

    if name in k8s_groups:
        generated_labels.update(k8s_groups[name])

    final_labels = server.labels.copy()
    if hetzner_config.update_server_labels_in_cloud:
        final_labels.update(generated_labels)

    return final_labels


def _update_cloud_server(server, name: str, labels: dict, hetzner_config: HetznerInventoryConfig) -> None:
    """Update cloud server name and/or labels via API"""
    update_args = {}

    if hetzner_config.update_server_names_in_cloud:
        update_args["name"] = name

    if hetzner_config.update_server_labels_in_cloud:
        update_args["labels"] = labels

    if update_args:
        server.update(**update_args)


def _create_cloud_host_entry(
    server,
    name: str,
    priv_ip: str | None,
    ipv4: str,
    product: str,
    labels: dict,
    hetzner_config: HetznerInventoryConfig,
    hosts_init: dict,
    force: bool,
) -> dict:
    """Create cloud host dictionary entry"""
    region = server.datacenter.name[0:3].lower()
    zone = server.datacenter.location.name.lower()
    dc = server.datacenter.name.lower().replace("-", "")
    group = f"{hetzner_config.cluster_prefix}{server.id % 4}"

    hostname = hetzner_config.hostname_format.format(
        name=name, group=group, dc=dc, domain_name=hetzner_config.domain_name
    )

    ssh_user = _get_ssh_user(server.id, hetzner_config)

    host = {
        "name": name,
        "ip": priv_ip,
        "ip_vlan": priv_ip,
        "ansible_ssh_host": ipv4,
        "ansible_user": ssh_user,
        "hostname": hostname,
        "model": product,
        "protected": True,
        "region": region,
        "zone": zone,
        "server_info": {
            "labels": labels,
            "dc": dc,
            "id": server.id,
            "group": group,
            "hetzner": {
                "options": "",
                "public_ip": ipv4,
                "current_name": server.name,
                "product": server.server_type.name.upper(),
                "datacenter": server.datacenter.name.upper(),
            },
        },
    }

    if name in hosts_init and not force:
        if "ip" in hosts_init[name] and hosts_init[name]["ip"]:
            host["ip"] = hosts_init[name]["ip"]
        if "ip_vlan" in hosts_init[name] and hosts_init[name]["ip_vlan"]:
            host["ip_vlan"] = hosts_init[name]["ip_vlan"]

    return host


def gen_cloud(
    hosts_init,
    token: str,
    hetzner_config: HetznerInventoryConfig,
    env="production",
    force=False,
    process_all_hosts: bool = False,
):
    client = Client(token=token)
    hcloud_servers = client.servers.get_all()
    hosts = {}
    hids = hosts_by_id(list(hosts_init.values()))

    servers = _filter_cloud_servers(hcloud_servers, hetzner_config, process_all_hosts)
    k8s_groups = prep_k8s()

    table = Table(
        highlight=True,
        title="Hetzner Cloud servers",
        title_justify="left",
        title_style="bold magenta",
        row_styles=["bold", "none"],
    )
    table.add_column("#", justify="left")
    table.add_column("ID", justify="left")
    table.add_column("Name", justify="left")
    table.add_column("Product", justify="left")
    table.add_column("Public IP", justify="left")
    table.add_column("Priv IP", justify="left")
    table.add_column("Vlan IP", justify="left")
    table.add_column("Labels", justify="left")
    table.add_column("Zone", justify="left")
    live = Live(table, refresh_per_second=4)
    live.start()

    for i, number in enumerate(sorted(servers.keys())):
        server = servers[number]
        product = server.server_type.name.lower().replace("-", "").replace(" ", "")
        region = server.datacenter.name[0:3].lower()
        dc = server.datacenter.name.lower().replace("-", "")
        group = f"{hetzner_config.cluster_prefix}{number % 4}"

        name = _get_cloud_server_name(server, hids, product, hetzner_config, force)

        priv_ip = server.private_net[0].ip if server.private_net else None
        ipv4 = server.public_net.ipv4.ip

        # Prepare and update labels
        final_labels = _prep_cloud_labels(server, group, name, k8s_groups, hetzner_config)
        _update_cloud_server(server, name, final_labels, hetzner_config)

        # Create host entry
        host = _create_cloud_host_entry(
            server, name, priv_ip, ipv4, product, final_labels, hetzner_config, hosts_init, force
        )

        labels_str = ", ".join([f"{k}={v}" for k, v in final_labels.items()])
        table.add_row(
            str(i + 1),
            str(number),
            name,
            product,
            f"[pale_turquoise1]{ipv4}",
            host["ip"],
            f"[sky_blue1]{host['ip_vlan']}",
            f"[pale_turquoise1]{labels_str}",
            f"[sea_green1]{region.upper()}[default] {dc}",
        )
        hosts[name] = host

    inventory = ansible_hosts(hosts, "hetzner_cloud")
    live.stop()
    with open(f"inventory/{env}/cloud.yaml", "w") as f:
        f.write(yaml.dump(inventory))


def ssh_config(env: str, hetzner_config: HetznerInventoryConfig):
    # This function still reads fixed paths. Consider making them configurable if needed.
    configs = []
    try:
        with open(f"inventory/{env}/hosts.yaml") as f:
            inventory = yaml.safe_load(f.read())
            configs = _ssh_config(inventory["all"]["hosts"], hetzner_config, "Robot")
    except FileNotFoundError:
        print(f"Warning: inventory/{env}/hosts.yaml not found. SSH config for robot hosts will be skipped.")
        inventory = {"all": {"hosts": {}}}  # Provide default structure to avoid errors
    except yaml.YAMLError as e:
        print(f"Warning: Error parsing inventory/{env}/hosts.yaml: {e}. SSH config for robot hosts will be skipped.")
        inventory = {"all": {"hosts": {}}}

    try:
        with open(f"inventory/{env}/cloud.yaml") as f:
            inventory_cloud = yaml.safe_load(f.read())
            configs += _ssh_config(inventory_cloud["all"]["hosts"], hetzner_config, "Cloud")
    except FileNotFoundError:
        print(f"Warning: inventory/{env}/cloud.yaml not found. SSH config for cloud hosts will be skipped.")
        inventory_cloud = {"all": {"hosts": {}}}
    except yaml.YAMLError as e:
        print(f"Warning: Error parsing inventory/{env}/cloud.yaml: {e}. SSH config for cloud hosts will be skipped.")
        inventory_cloud = {"all": {"hosts": {}}}

    with open("config-hetzner", "w") as f:  # Consider making output path configurable
        for c in configs:
            f.write(c + "\n")
