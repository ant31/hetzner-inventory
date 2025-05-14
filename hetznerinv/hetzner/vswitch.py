from hetzner import RobotError

__all__ = ['Failover', 'FailoverManager']


class Vswitch(object):
    id = None
    vlan = None
    server = []
    subnet = []
    cloud_network = []
    name = None

    def __repr__(self):
        return "vswitch-id: %s, vlan-id: %s, servers: %s" % (
            self.id, self.vlan, len(self.server))

    def __init__(self, data):
        for attr, value in data.items():
            if hasattr(self, attr):
                setattr(self, attr, value)



class VswitchManager(object):
    def __init__(self, conn, servers):
        self.conn = conn
        self.servers = servers

    def list(self):
        vswitchs = {}
        try:
            vswitches = self.conn.get('/vswitch')
        except RobotError as err:
            if err.status == 404:
                return vswitchs
            else:
                raise
        for v in vswitches:
            vswitch = Vswitch(self.conn.get('/vswitch/%s' % v['id']))
            vswitchs[vswitch.id] = vswitch
        return vswitchs

    def add_servers(self, switch, servers):
        ips = [s.ip for s in servers if s.ip != None]
        return self.conn.post("vswitch/%s/server" % switch.id,  {'server': ips})
