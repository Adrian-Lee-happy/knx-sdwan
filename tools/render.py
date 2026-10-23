#!/usr/bin/env python3
"""Render reviewed templates locally. No router or network operations."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    'home_cidr', 'home_router_ip', 'private_lan_cidr', 'wg_cidr',
    'server_wg_ip', 'client_wg_ip', 'endpoint_host', 'wg_port',
    'physical_wan_device', 'server_peer_section', 'client_peer_section',
    'openclash_compat_enabled', 'openclash_table', 'openclash_mark',
    'openclash_tun_device',
}
RFC1918 = tuple(ipaddress.ip_network(p) for p in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def parameters(cfg):
    if not isinstance(cfg, dict) or set(cfg) != REQUIRED:
        raise ValueError('Configuration keys must exactly match site.example.json')
    nets = []
    for field in ('home_cidr', 'private_lan_cidr', 'wg_cidr'):
        if not isinstance(cfg[field], str):
            raise ValueError('Invalid network field: ' + field)
        n = ipaddress.ip_network(cfg[field], strict=True)
        if n.version != 4 or not 8 <= n.prefixlen <= 30 or not any(n.subnet_of(p) for p in RFC1918):
            raise ValueError('Canonical RFC1918 IPv4 network required: ' + field)
        nets.append(n)
    if any(a.overlaps(b) for i, a in enumerate(nets) for b in nets[i + 1:]):
        raise ValueError('Home, private maintenance and WG networks must not overlap')
    for field, net in (('home_router_ip', nets[0]), ('server_wg_ip', nets[2]), ('client_wg_ip', nets[2])):
        if not isinstance(cfg[field], str):
            raise ValueError('IPv4 address must be a string: ' + field)
        a = ipaddress.ip_address(cfg[field])
        if a.version != 4 or a not in net or a in (net.network_address, net.broadcast_address):
            raise ValueError('Invalid host address: ' + field)
    if cfg['server_wg_ip'] == cfg['client_wg_ip']:
        raise ValueError('Distinct tunnel host addresses required')
    for field in ('server_peer_section', 'client_peer_section'):
        if not isinstance(cfg[field], str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,47}', cfg[field]):
            raise ValueError('Invalid UCI section identifier: ' + field)
    for field in ('physical_wan_device', 'openclash_tun_device'):
        if not isinstance(cfg[field], str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', cfg[field]):
            raise ValueError('Invalid interface identifier: ' + field)
    host = cfg['endpoint_host']
    if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}', host):
        raise ValueError('ASCII DNS hostname required')
    if type(cfg['wg_port']) is not int or not 1024 <= cfg['wg_port'] <= 65535:
        raise ValueError('WG UDP port must be an integer from 1024 to 65535')
    if type(cfg['openclash_table']) is not int or not 256 <= cfg['openclash_table'] <= 32765:
        raise ValueError('Invalid optional OpenClash table')
    if not isinstance(cfg['openclash_mark'], str) or not re.fullmatch(r'0x[0-9a-f]{1,8}', cfg['openclash_mark']):
        raise ValueError('Invalid optional OpenClash fwmark')
    if type(cfg['openclash_compat_enabled']) is not bool:
        raise ValueError('Compatibility flag must be a boolean')
    values = {key.upper(): str(value) for key, value in cfg.items()}
    values['WG_PREFIX'] = str(nets[2].prefixlen)
    return values


def render(cfg, output):
    values = parameters(cfg)
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Output must be outside the repository to protect private site data')
    if output.exists():
        raise ValueError('Output already exists; choose a new directory')
    plans = []
    for role in ('r86s', 'cudy'):
        for base in ('common', role):
            for p in sorted((ROOT / 'src' / base).rglob('*')):
                if p.is_symlink():
                    raise ValueError('Symlinks are not allowed')
                if not p.is_file():
                    continue
                if role == 'r86s' and p.name == '95-knx-policy.in' and not cfg['openclash_compat_enabled']:
                    continue
                rel = p.relative_to(ROOT / 'src' / base)
                text = p.read_text(encoding='utf-8')
                if p.name.endswith('.in'):
                    rel = rel.with_name(rel.name[:-3])
                    def substitute(m):
                        if m[1] not in values:
                            raise ValueError('Unrecognized template parameter: ' + m[1])
                        return values[m[1]]
                    text = re.sub(r'@([A-Z][A-Z0-9_]*)@', substitute, text)
                if re.search(r'@[A-Z][A-Z0-9_]*@', text):
                    raise ValueError('Unresolved parameter in ' + str(p.relative_to(ROOT)))
                plans.append((output / role / 'rootfs' / rel, text))
        for p in sorted((ROOT / 'integration' / role).glob('*.in')):
            text = p.read_text(encoding='utf-8')
            text = re.sub(r'@([A-Z][A-Z0-9_]*)@', lambda m: values[m[1]], text)
            plans.append((output / role / 'integration' / p.name[:-3], text))
    paths = [str(p) for p, _ in plans]
    if len(paths) != len(set(paths)):
        raise ValueError('Overlapping generated paths')
    output.mkdir(mode=0o700)
    manifest = []
    for p, text in plans:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_text(text, encoding='utf-8', newline='\n')
        relative = p.relative_to(output).as_posix()
        executable = text.startswith('#!') or '/usr/libexec/rpcd/' in relative
        mode = 0o700 if executable else 0o600
        if '/www/' in relative or '/usr/share/' in relative:
            mode = 0o644
        p.chmod(mode)
        manifest.append({'path': relative, 'mode': oct(mode), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    (output / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Rendered %d files into a new local bundle. No router contacted.' % len(plans))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        render(json.loads(args.config.read_text(encoding='utf-8-sig')), args.output)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, 'Refused: %s\n' % exc)
