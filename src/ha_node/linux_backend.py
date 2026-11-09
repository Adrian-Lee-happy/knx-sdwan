"""Linux rule compiler and narrowly scoped executor for HA maintenance.

WireGuard device creation and controller enrollment are intentionally separate.
The backend owns one nft table and two policy rules, never the host default route.
"""
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import json
import re
import subprocess

from node_policy import Candidate, private_network

TABLE = 'ha_remote_node'
OWNER = 'ha-remote-node/v1'


def run(argv, text=None, check=True):
    return subprocess.run(argv, input=text, text=True, capture_output=True,
                          timeout=10, check=check)


@dataclass(frozen=True)
class Config:
    home: str
    tunnel: str
    server: str
    wg_interface: str = 'wg_ha'
    physical_interface: str = 'end0'
    route_table: int = 21890
    rule_priority: int = 21890
    agent_port: int = 22223

    def validate(self):
        h = private_network(self.home)
        t, s = ip_address(self.tunnel), ip_address(self.server)
        if t.version != 4 or s.version != 4 or t == s or t in h or s in h:
            raise ValueError('distinct IPv4 tunnel addresses outside home LAN required')
        from node_policy import PRIVATE
        if not any(t in n for n in PRIVATE) or not any(s in n for n in PRIVATE):
            raise ValueError('private tunnel addresses required')
        for name in (self.wg_interface, self.physical_interface):
            if not re.fullmatch('[a-zA-Z0-9_.-]{1,15}', name):
                raise ValueError('invalid interface')
        if self.wg_interface == self.physical_interface:
            raise ValueError('interfaces must differ')
        if not 20000 <= self.route_table <= 29999 or not 20000 <= self.rule_priority <= 29998:
            raise ValueError('dedicated routing range required')
        if not 1024 <= self.agent_port <= 65535:
            raise ValueError('invalid Agent port')
        return self


def discover(cfg, runner=run, boot_path='/proc/sys/kernel/random/boot_id'):
    """Inspect one explicit wired interface; never infer a site from docker0."""
    cfg.validate()
    addr = json.loads(runner(['ip', '-j', '-4', 'addr', 'show', 'dev', cfg.physical_interface]).stdout)
    routes = json.loads(runner(['ip', '-j', '-4', 'route', 'show', 'dev', cfg.physical_interface]).stdout)
    if len(addr) != 1 or 'LOWER_UP' not in addr[0].get('flags', []):
        raise ValueError('physical link unavailable')
    ips = [a for a in addr[0].get('addr_info', []) if a.get('scope') == 'global']
    defaults = [r for r in routes if r.get('dst') == 'default' and r.get('gateway')]
    if len(ips) != 1 or len(defaults) != 1:
        raise ValueError('single physical address and gateway required')
    a, g = ips[0], defaults[0]['gateway']
    network = str(ip_network(a['local'] + '/' + str(a['prefixlen']), strict=False))
    if not any(r.get('dst') == network and r.get('scope') == 'link' for r in routes):
        raise ValueError('connected route missing')
    neighbors = json.loads(runner(['ip', '-j', '-4', 'neigh', 'show', g,
                                  'dev', cfg.physical_interface]).stdout)
    good = [n for n in neighbors if n.get('lladdr') and not
            set(n.get('state', [])).intersection({'FAILED', 'INCOMPLETE'})]
    if len(good) != 1:
        raise ValueError('gateway neighbor has not been verified')
    with open(boot_path, encoding='ascii') as f:
        boot = f.read().strip()
    c = Candidate(network, a['local'], g, cfg.physical_interface, good[0]['lladdr'], boot)
    # Also reserve the HA Docker networks: routes must not capture them.
    # Conflict authorization belongs to Agent; preserve the observed subnet so
    # the controller can display a useful refusal without authorizing it.
    return c.validate([])


def firewall(cfg):
    """Start OFF, including already-established business sessions.

    This early chain may DROP; ACCEPT still needs Docker's forwarding permission.
    Management has no blanket ESTABLISHED exception for HA-initiated sessions.
    """
    cfg.validate()
    w, h, t, s, p = cfg.wg_interface, cfg.home, cfg.tunnel, cfg.server, cfg.agent_port
    return f'''table inet {TABLE} {{
 comment "{OWNER}"
 set lease {{ type ifname; flags timeout; timeout 45s; }}
 set customer {{ type ipv4_addr; flags interval; }}
 chain input {{
  type filter hook input priority -20; policy accept;
  iifname "{w}" meta nfproto ipv6 drop
  iifname "{w}" ct state invalid drop
  iifname "{w}" ip saddr {{ {h}, {s} }} ip daddr {t} tcp dport {{ 80, 8123, 22222, {p} }} accept
  iifname "{w}" ip saddr {{ {h}, {s} }} ip daddr {t} icmp type echo-request accept
  iifname "{w}" iifname @lease ip saddr {h} ip daddr @customer accept
  iifname "{w}" drop
 }}
 chain output {{
  type filter hook output priority -20; policy accept;
  oifname "{w}" meta nfproto ipv6 drop
  oifname "{w}" ct state invalid drop
  oifname "{w}" ip saddr {t} ip daddr {{ {h}, {s} }} ct direction reply ct state established,related ct original ip saddr {{ {h}, {s} }} accept
  oifname "{w}" oifname @lease ip saddr @customer ip daddr {h} ct direction reply ct state established,related ct original ip saddr {h} accept
  oifname "{w}" drop
 }}
 chain forward {{
  type filter hook forward priority -20; policy accept;
  iifname "{w}" meta nfproto ipv6 drop
  oifname "{w}" meta nfproto ipv6 drop
  iifname "{w}" ct state invalid drop
  oifname "{w}" ct state invalid drop
  iifname "{w}" iifname @lease oifname "{cfg.physical_interface}" ip saddr {h} ip daddr @customer ct direction original accept
  oifname "{w}" oifname @lease iifname "{cfg.physical_interface}" ip saddr @customer ip daddr {h} ct direction reply ct state established,related ct original ip saddr {h} accept
  iifname "{w}" drop
  oifname "{w}" drop
 }}
 chain node_snat {{
  type nat hook postrouting priority 95; policy accept;
  iifname "{w}" iifname @lease oifname "{cfg.physical_interface}" ip saddr {h} ip daddr @customer masquerade
 }}
}}
'''


class Backend:
    def __init__(self, cfg, runner=run):
        self.cfg = cfg.validate()
        self.run = runner

    def owns_table(self):
        r = self.run(['nft', '-j', 'list', 'table', 'inet', TABLE], check=False)
        if r.returncode:
            # Missing tools/permissions must never be interpreted as absence.
            if 'No such file or directory' in r.stderr:
                return False
            raise RuntimeError('cannot inspect firewall table')
        objects = json.loads(r.stdout)['nftables']
        if not any(x.get('table', {}).get('comment') == OWNER for x in objects):
            raise RuntimeError('firewall table belongs to another application')
        return True

    def install_off(self):
        exists = self.owns_table()
        text = ('delete table inet ' + TABLE + '\n' if exists else '') + firewall(self.cfg)
        self.run(['nft', '-c', '-f', '-'], text)
        self.run(['nft', '-f', '-'], text)

    def close(self):
        if not self.owns_table():
            raise RuntimeError('guard absent: cannot claim business safely OFF')
        self.run(['nft', '-f', '-'], f'flush set inet {TABLE} lease\nflush set inet {TABLE} customer\n')

    def open(self, candidate):
        self.close()
        c = candidate.validate([self.cfg.home, self.cfg.tunnel + '/32', self.cfg.server + '/32',
                                '172.30.32.0/23', '172.30.232.0/23'])
        if c.interface != self.cfg.physical_interface:
            raise ValueError('wrong physical interface')
        # One atomic transaction: old sessions cannot outlive the kernel lease.
        self.run(['nft', '-f', '-'], f'add element inet {TABLE} customer {{ {c.network} }}\n'
                 f'add element inet {TABLE} lease {{ "{self.cfg.wg_interface}" timeout 45s }}\n')

    def renew(self):
        # Do not flush first: renewal is a single atomic replacement transaction.
        if not self.owns_table():
            raise RuntimeError('guard absent')
        present = self.run(['nft', 'get', 'element', 'inet', TABLE, 'lease',
                            '{ "' + self.cfg.wg_interface + '" }'], check=False)
        if present.returncode:
            raise RuntimeError('kernel lease lost; explicit activation required')
        self.run(['nft', '-f', '-'], f'delete element inet {TABLE} lease {{ "{self.cfg.wg_interface}" }}\n'
                 f'add element inet {TABLE} lease {{ "{self.cfg.wg_interface}" timeout 45s }}\n')

    def route_plan(self, candidate):
        candidate.validate([self.cfg.home, self.cfg.tunnel + '/32', self.cfg.server + '/32'])
        if candidate.interface != self.cfg.physical_interface:
            raise ValueError('wrong interface')
        c = self.cfg
        return [
            ['ip', '-4', 'route', 'add', 'unreachable', 'default', 'table', str(c.route_table), 'metric', '42760'],
            ['ip', '-4', 'route', 'add', c.home, 'dev', c.wg_interface, 'table', str(c.route_table)],
            ['ip', '-4', 'rule', 'add', 'pref', str(c.rule_priority), 'from', candidate.network,
             'to', c.home, 'lookup', str(c.route_table)],
        ]
