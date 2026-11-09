"""Dedicated WireGuard interface ownership and management-only bootstrap."""
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import urllib.parse
import urllib.request

from linux_backend import Config, Backend, OWNER, run
from process_supervisor import run_service

STATE=Path('/state')


def endpoint(host):
    try:
        value=ipaddress.ip_address(host)
        if not value.is_global:raise ValueError('public endpoint required')
        return str(value)
    except ValueError:
        pass
    import re
    if not re.fullmatch(r'[a-zA-Z0-9.-]{1,253}',host):raise ValueError('invalid endpoint hostname')
    errors=[]
    for resolver in ('https://cloudflare-dns.com/dns-query','https://dns.google/resolve'):
        try:
            url=resolver+'?'+urllib.parse.urlencode({'name':host,'type':'A'})
            req=urllib.request.Request(url,headers={'Accept':'application/dns-json','User-Agent':'HA-remote-node/1'})
            with urllib.request.urlopen(req,timeout=8) as r:data=json.load(r)
            for answer in data.get('Answer',[]):
                if answer.get('type')==1:
                    address=ipaddress.ip_address(answer['data'])
                    if address.version==4 and address.is_global:return str(address)
        except Exception as e:errors.append(type(e).__name__)
    raise RuntimeError('public endpoint resolution unavailable')


def keys():
    STATE.mkdir(mode=0o700,exist_ok=True);STATE.chmod(0o700)
    key=STATE/'wg_private'
    if not key.exists():key.write_text(run(['wg','genkey']).stdout);key.chmod(0o600)
    pub=run(['wg','pubkey'],key.read_text()).stdout.strip()
    if not (STATE/'ssh_host_ed25519_key').exists():
        run(['ssh-keygen','-t','ed25519','-N','','-f',str(STATE/'ssh_host_ed25519_key')])
    if not (STATE/'consent_token').exists():
        (STATE/'consent_token').write_text(secrets.token_urlsafe(40));(STATE/'consent_token').chmod(0o600)
    print(json.dumps({'wg_public':pub,'ssh_public':(STATE/'ssh_host_ed25519_key.pub').read_text().strip()}))


def cleanup(cfg):
    import shlex
    links=json.loads(run(['ip','-j','link','show'],check=True).stdout)
    link=next((x for x in links if x['ifname']==cfg.wg_interface),None)
    if link is None:return
    if link.get('ifalias')!=OWNER:raise RuntimeError('existing interface is not ours')
    r=run(['iptables','-S','DOCKER-USER'],check=False)
    if r.returncode==0:
        for line in r.stdout.splitlines():
            words=shlex.split(line)
            if 'ha-node-c-business' in words and cfg.wg_interface in words and words[:2]==['-A','DOCKER-USER']:
                words[0]='-D';run(['iptables']+words)
    for table,pref in ((cfg.route_table-1,cfg.rule_priority-1),(cfg.route_table,cfg.rule_priority)):
        r=run(['ip','-j','-4','route','show','table',str(table)],check=False)
        routes=json.loads(r.stdout) if r.returncode==0 else []
        if any(x.get('dst') not in (cfg.home,'default') or
               (x.get('type')!='unreachable' and x.get('dev')!=cfg.wg_interface) for x in routes):
            raise RuntimeError('routing ownership changed')
        rules=json.loads(run(['ip','-j','-4','rule','show']).stdout)
        owned=[x for x in rules if x.get('priority')==pref]
        if any(str(x.get('table'))!=str(table) for x in owned):raise RuntimeError('rule ownership changed')
        for x in owned:run(['ip','-4','rule','del','pref',str(pref),'lookup',str(table)])
        for x in routes:
            cmd=['ip','-4','route','del']
            if x.get('type')=='unreachable':cmd+=['unreachable']
            cmd += [x['dst'],'table',str(table)]
            run(cmd)
    run(['ip','-4','route','del',cfg.server+'/32','dev',cfg.wg_interface],check=False)
    run(['ip','link','del','dev',cfg.wg_interface])


def start():
    data=json.loads((STATE/'config.json').read_text());cfg=Config(**data['network']).validate()
    Backend(cfg).install_off();cleanup(cfg)
    # Dedicated management resources must be free before we create anything.
    rules=json.loads(run(['ip','-j','-4','rule','show']).stdout)
    if any(x.get('priority') in (cfg.rule_priority-1,cfg.rule_priority) for x in rules):
        raise RuntimeError('routing priority conflict')
    for table in (cfg.route_table-1,cfg.route_table):
        r=run(['ip','-j','-4','route','show','table',str(table)],check=False)
        if r.returncode==0 and json.loads(r.stdout):raise RuntimeError('routing table conflict')
    ep=endpoint(data['endpoint_host'])
    port=data['endpoint_port']
    if not isinstance(port,int) or not 1<=port<=65535:raise ValueError('invalid endpoint port')
    import base64
    if len(base64.b64decode(data['server_public_key'],validate=True))!=32:raise ValueError('invalid server key')
    run(['ip','link','add',cfg.wg_interface,'type','wireguard'])
    run(['ip','link','set','dev',cfg.wg_interface,'alias',OWNER])
    try:
        run(['wg','set',cfg.wg_interface,'private-key',str(STATE/'wg_private'),
             'peer',data['server_public_key'],'allowed-ips',cfg.home+','+cfg.server+'/32',
             'endpoint',ep+':'+str(port),'persistent-keepalive','25'])
        run(['ip','addr','add',cfg.tunnel+'/32','dev',cfg.wg_interface])
        run(['ip','link','set','dev',cfg.wg_interface,'mtu','1380','up'])
        run(['ip','-4','route','add',cfg.server+'/32','dev',cfg.wg_interface])
        run(['ip','-4','route','add','unreachable','default','table',str(cfg.route_table-1),'metric','42760'])
        run(['ip','-4','route','add',cfg.home,'dev',cfg.wg_interface,'table',str(cfg.route_table-1)])
        run(['ip','-4','rule','add','pref',str(cfg.rule_priority-1),'from',cfg.tunnel+'/32',
             'to',cfg.home,'lookup',str(cfg.route_table-1)])
        text=f'''Port {cfg.agent_port}
ListenAddress {cfg.tunnel}
HostKey /state/ssh_host_ed25519_key
AuthorizedKeysFile /state/authorized_keys
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitTTY no
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
ForceCommand /usr/local/bin/python /app/agent_service.py relay
LogLevel ERROR
'''
        (STATE/'sshd_config').write_text(text);(STATE/'sshd_config').chmod(0o600)
        # Unlock public-key access only; no usable password hash is installed.
        shadow=Path('/etc/shadow')
        lines=shadow.read_text().splitlines()
        shadow.write_text('\n'.join(':'.join([a[0],'*',*a[2:]]) if a[0]=='root' else ':'.join(a)
                                    for a in (l.split(':') for l in lines))+'\n')
        Path('/run/sshd').mkdir(exist_ok=True)
        run(['/usr/sbin/sshd','-t','-f','/state/sshd_config'])
        run_service([sys.executable,'/app/agent_service.py'])
    finally:
        Backend(cfg).close();cleanup(cfg)


if __name__=='__main__':
    if sys.argv[1:]==['keys']:keys()
    elif sys.argv[1:]==['cleanup']:
        cfg=Config(**json.loads((STATE/'config.json').read_text())['network']);Backend(cfg).close();cleanup(cfg)
    else:start()
