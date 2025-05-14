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


def list_all_hosts(
    robot: Robot,
    hetzner_config: HetznerInventoryConfig,
    hosts_init=None,
    force=False,
    process_all_hosts: bool = False,
):
    if hosts_init is None:
        hosts_init = {}
    vlan_id = hetzner_config.vlan_id
    hosts = {}
    servers = {}
    hids = hosts_by_id(list(hosts_init.values()))
    privips = {}
    vlanips = {}
    for server in robot.servers:
        if server.ip is None:
            continue

        if not process_all_hosts:
            if server.ip in hetzner_config.ignore_hosts_ips:
                continue
            if str(server.number) in hetzner_config.ignore_hosts_ids:
                continue
        servers[server.number] = server

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
    for i, number in enumerate(sorted(list(servers.keys()))):
        options = ""
        server = servers[number]
        product = server.product.lower().replace("-", "").replace(" ", "")
        if product == "serverauction":
            product = ""
        if product.startswith("dellpoweredge\u2122r6515"):
            product = product.split("dellpoweredge\u2122r6515")[1]
        if product.startswith("dellpoweredge\u2122r6615"):
            product = product.split("dellpoweredge\u2122r6615")[1]

        region = server.datacenter[0:3].lower()
        zone = server.datacenter[0:4].lower()
        dc = server.datacenter.lower().replace("-", "")

        # Ensure dc exists in cluster_subnets, or handle potential KeyError
        if dc not in hetzner_config.cluster_subnets:
            live.console.print(f"Warning: DC '{dc}' not in cluster_subnets config. Skipping server {server.number}.")
            continue
        if vlan_id not in hetzner_config.cluster_subnets:
            live.console.print(
                f"Warning: VLAN ID '{vlan_id}' not in cluster_subnets config. Skipping server {server.number}."
            )
            continue

        if str(server.number) in hetzner_config.product_options:
            options = hetzner_config.product_options[str(server.number)]
        elif product in hetzner_config.product_options:
            options = hetzner_config.product_options[product]

        group = f"{hetzner_config.cluster_prefix}{server.number % 4}"
        last_ipvlan = hetzner_config.cluster_subnets[vlan_id].start
        last_privip = hetzner_config.cluster_subnets[dc].start
        name = f"{server.number}-{product}{options}"
        if number in hids:
            name = hids[number]["name"]

        if hetzner_config.cluster_subnets[dc].privlink and name not in hetzner_config.no_privlink_hostnames:
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

        # print(server, priv_ip, last_ipvlan)
        # @TODO don't use group to subnet
        hetzner_config.cluster_subnets[dc].start = str(IPv4Address(last_privip) + 1)
        hetzner_config.cluster_subnets[vlan_id].start = str(IPv4Address(last_ipvlan) + 1)

        while hetzner_config.cluster_subnets[dc].start in privips:
            hetzner_config.cluster_subnets[dc].start = str(IPv4Address(hetzner_config.cluster_subnets[dc].start) + 1)

        while hetzner_config.cluster_subnets[vlan_id].start in vlanips:
            current_ip = hetzner_config.cluster_subnets[vlan_id].start
            hetzner_config.cluster_subnets[vlan_id].start = str(IPv4Address(current_ip) + 1)

        hostname = hetzner_config.hostname_format.format(
            name=name, group=group, dc=dc, domain_name=hetzner_config.domain_name
        )
        host = {
            "name": name,
            "ip": priv_ip,
            "ip_vlan": last_ipvlan,
            "ansible_ssh_host": server.ip,
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
        hosts[name] = host
        table.add_row(
            str(i + 1),
            str(server.number),
            name,
            server.product,
            f"[pale_turquoise1]{server.ip}",
            priv_ip,
            f"[sky_blue1]{last_ipvlan}",
            f"[sea_green1]{region.upper()}[default] {dc}",
        )
    live.stop()
    return hosts


def ansible_hosts(hosts, hetzner_group):
    inventory = {"all": {"hosts": {}}}
    ordered_keys = sorted(list(hosts.keys()))
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
                    "kadmin",
                    hetzner_config.ssh_identity_file,
                )
                template = f"""
#{s["hostname"]}
Host {hostname_alias}
    HostName {s["ansible_ssh_host"]}
    User kadmin
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
):
    if hosts_inv is None:
        hosts_inv = {}
    hosts = list_all_hosts(robot, hetzner_config, hosts_inv, process_all_hosts=process_all_hosts)
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
    servers = {}
    hosts = {}
    hids = hosts_by_id(list(hosts_init.values()))
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

    for s in hcloud_servers:
        if s.public_net.ipv4.ip is None:
            continue
        if not process_all_hosts:
            if s.public_net.ipv4.ip in hetzner_config.ignore_hosts_ips:
                continue
            if str(s.id) in hetzner_config.ignore_hosts_ids:
                continue
        servers[s.id] = s
    k8s_groups = prep_k8s()

    for i, number in enumerate(sorted(list(servers.keys()))):
        server = servers[number]
        product = server.server_type.name.lower().replace("-", "").replace(" ", "")
        region = server.datacenter.name[0:3].lower()
        zone = server.datacenter.location.name.lower()
        dc = server.datacenter.name.lower().replace("-", "")
        group = f"{hetzner_config.cluster_prefix}{number % 4}"
        # Use str(number) for dict lookup as Pydantic model keys are strings
        name = hetzner_config.cloud_instance_names.get(str(number), f"{number}-{product}")
        if number in hids and not force:
            name = hids[number]["name"]  # This might override cloud_instance_names lookup if ID was in hosts_init.
            # Consider if cloud_instance_names should take precedence.
            # For now, matching original logic.

        if server.private_net:
            priv_ip = server.private_net[0].ip
        else:
            priv_ip = None
        ipv4 = server.public_net.ipv4.ip

        # The original 'hostname' variable was generated based on the script-generated 'name'.
        # We will regenerate it later if needed, based on name_for_host_object_and_api.
        # original_hostname_generated_by_script = hetzner_config.hostname_format.format(
        # name=name, group=group, dc=dc, domain_name=hetzner_config.domain_name
        # )

        pg = server.placement_group  # pg is defined here

        # 1. Determine the name to be used for the host object and potentially for API update.
        # The 'name' variable at this point holds the generated/intended name from earlier logic.
        name_for_host_object_and_api = name
        if not hetzner_config.update_server_names_in_cloud:
            # If not updating the name in the cloud, the inventory should reflect the actual server name.
            name_for_host_object_and_api = server.name

        # 2. Prepare purely generated labels (based on group, placement group, k8s).
        # These are the labels this script *wants* to set or ensure are present.
        # 'name' (the generated/intended name) is used as the key for k8s_groups.
        generated_labels_component = {"group": group}
        if pg:
            generated_labels_component.update(pg.labels)
        if name in k8s_groups:  # 'name' is the generated/intended name
            generated_labels_component.update(k8s_groups[name])

        # 3. Determine the final set of labels for the host object and for API update.
        # Start with a copy of the server's current labels from the API.
        final_labels_for_host_and_api = server.labels.copy()

        if hetzner_config.update_server_labels_in_cloud:
            # If updating labels in the cloud, merge the generated labels into the current ones.
            # Generated labels will overwrite existing ones if keys conflict.
            final_labels_for_host_and_api.update(generated_labels_component)
        # If not updating labels in the cloud, final_labels_for_host_and_api remains a copy of server.labels.
        # This ensures the host object in the inventory reflects the actual labels on the server.

        # 4. Prepare arguments for the API update call.
        update_args = {}
        if hetzner_config.update_server_names_in_cloud:
            # API name update uses the script-generated 'name' (held in 'name' variable at the start of this block).
            update_args["name"] = name

        if hetzner_config.update_server_labels_in_cloud:
            # API labels update uses the merged set.
            update_args["labels"] = final_labels_for_host_and_api

        # 5. Perform the API update if there are any changes to make.
        if update_args:
            server.update(**update_args)

        # 6. Construct the host object using the determined names and labels.
        # The hostname (FQDN) should be based on the name that will be used in the inventory.
        hostname_generated = hetzner_config.hostname_format.format(
            name=name_for_host_object_and_api,  # This is the name appearing in the inventory
            group=group,
            dc=dc,
            domain_name=hetzner_config.domain_name,
        )

        host = {
            "name": name_for_host_object_and_api,  # Name for inventory key and ansible
            "ip": priv_ip,
            "ip_vlan": priv_ip,
            "ansible_ssh_host": ipv4,
            "hostname": hostname_generated,  # Generated FQDN
            "model": product,
            "protected": True,
            "region": region,
            "zone": zone,
            "server_info": {
                "labels": final_labels_for_host_and_api,  # Final labels for inventory
                "dc": dc,
                "id": number,
                "group": group,
                "hetzner": {
                    "options": "",
                    "public_ip": ipv4,
                    "current_name": server.name,  # Always store the actual current API name
                    "product": server.server_type.name.upper(),
                    "datacenter": server.datacenter.name.upper(),
                },
            },
        }
        if name in hosts_init and not force:  # hosts_init here refers to the function parameter
            if "ip" in hosts_init[name] and hosts_init[name]["ip"]:
                host["ip"] = hosts_init[name]["ip"]
            if "ip_vlan" in hosts_init[name] and hosts_init[name]["ip_vlan"]:
                host["ip_vlan"] = hosts_init[name]["ip_vlan"]
        labels_str = ", ".join([f"{k}={v}" for k, v in host["server_info"]["labels"].items()])
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
