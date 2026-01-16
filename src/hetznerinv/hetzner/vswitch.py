from typing import ClassVar

from . import RobotError

__all__ = ["Vswitch", "VswitchManager"]


class Vswitch:
    id = None
    vlan = None
    server: ClassVar[list] = []
    subnet: ClassVar[list] = []
    cloud_network: ClassVar[list] = []
    name = None

    def __repr__(self):
        return f"vswitch-id: {self.id}, vlan-id: {self.vlan}, servers: {len(self.server)}"

    def __init__(self, data):
        for attr, value in data.items():
            if hasattr(self, attr):
                setattr(self, attr, value)


class VswitchManager:
    def __init__(self, conn, servers):
        self.conn = conn
        self.servers = servers

    def list(self):
        vswitchs = {}
        try:
            vswitches = self.conn.get("/vswitch")
        except RobotError as err:
            if err.status == 404:
                return vswitchs
            else:
                raise
        for v in vswitches:
            vswitch = Vswitch(self.conn.get("/vswitch/{}".format(v["id"])))
            vswitchs[vswitch.id] = vswitch
        return vswitchs

    def add_servers(self, switch, servers):
        ips = [s.ip for s in servers if s.ip is not None]
        return self.conn.post(f"vswitch/{switch.id}/server", {"server": ips})
