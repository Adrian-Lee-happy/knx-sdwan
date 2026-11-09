"""Serialized Agent protocol; SSH transport must authenticate the caller.

The process owns its lease state. No reboot or process restart can restore ON.
"""
import time

from node_policy import BusinessGate


class Agent:
    METHODS = frozenset(('probe', 'activate', 'renew', 'deactivate'))

    def __init__(self, config, backend, routes, discovery, clock=time.monotonic):
        self.cfg = config.validate()
        self.backend, self.routes, self.discovery, self.clock = backend, routes, discovery, clock
        self.gate = BusinessGate([config.home, config.tunnel + '/32', config.server + '/32',
                                  '172.30.32.0/23', '172.30.232.0/23'])

    def close(self):
        self.gate.close()
        # Never remove routes before enforcing the early OFF firewall.
        self.backend.close()
        self.routes.close()

    def candidate(self):
        return self.discovery().validate(self.gate.reserved)

    def tick(self):
        if self.gate.candidate is None:
            return
        try:
            current = self.candidate()
            if not self.gate.active(current, self.clock()):
                self.close()
        except Exception:
            self.close()
            raise

    def local_set(self, enabled):
        self.gate.local_set(enabled)
        self.close()

    def handle(self, method, payload, *, source):
        # Authentication + management identity, never caller-supplied shell args.
        if source != self.cfg.server or method not in self.METHODS:
            return {'success': False, 'reason': 'source or method denied'}
        if not isinstance(payload, dict) or set(payload) - {'fingerprint'}:
            return {'success': False, 'reason': 'invalid request'}
        try:
            if method == 'deactivate':
                self.close()
                return {'success': True, 'active': False}
            raw = None
            try:
                raw = self.discovery()
                c = raw.validate(self.gate.reserved)
            except (ValueError, OSError):
                self.close()
                return {'success': method == 'probe', 'active': False,
                        'local_consent': self.gate.local_consent,
                        'candidate': {'valid': False, 'network': raw.network if raw else None,
                                      'reason': 'physical LAN invalid or overlaps reserved network'}}
            now = self.clock()
            if method == 'probe':
                active = self.gate.active(c, now)
                if not active:
                    self.close()
                return {'success': True, 'active': active, 'network': c.network if active else None,
                        'candidate': dict(c.__dict__, valid=True, fingerprint=c.fingerprint),
                        'local_consent': self.gate.local_consent}
            if method == 'activate':
                self.close()
                self.gate.activate(c, payload.get('fingerprint'), now)
                self.routes.open(c)
                self.backend.open(c)
            else:
                self.gate.renew(c, payload.get('fingerprint'), now)
                self.backend.renew()
            return {'success': True, 'active': True, 'network': c.network,
                    'fingerprint': c.fingerprint}
        except Exception:
            # Errors are deliberately generic: never disclose subprocess output,
            # key paths, environment or arbitrary filesystem content to clients.
            try:
                self.close()
            except Exception:
                return {'success': False, 'active': False, 'reason': 'cleanup failed; kernel lease expires within 45 seconds'}
            return {'success': False, 'active': False, 'reason': 'operation refused; business closed'}


class Routes:
    """Own only newly-added routes/rules; rollback in reverse order.

    Crash leftovers are refused rather than blindly flushed. Management routing
    is separate from this business lifecycle.
    """
    def __init__(self, backend):
        self.backend = backend
        self.undo = []

    def close(self):
        failed = []
        for command in reversed(self.undo):
            r = self.backend.run(command, check=False)
            if r.returncode and not any(s in r.stderr for s in ('No such process', 'No such file')):
                failed.append(command)
        self.undo = list(reversed(failed))
        if failed:
            raise RuntimeError('business route cleanup failed')

    def open(self, candidate):
        import json
        self.close()
        cfg = self.backend.cfg
        r = self.backend.run(['ip', '-j', '-4', 'route', 'show', 'table', str(cfg.route_table)], check=False)
        if r.returncode:
            if 'FIB table does not exist' not in r.stderr:
                raise RuntimeError('cannot inspect policy table')
        elif json.loads(r.stdout):
            raise RuntimeError('policy table occupied')
        rules = json.loads(self.backend.run(['ip', '-j', '-4', 'rule', 'show']).stdout)
        if any(x.get('priority') == cfg.rule_priority for x in rules):
            raise RuntimeError('policy priority occupied')
        try:
            for command in self.backend.route_plan(candidate):
                self.backend.run(command)
                undo = command.copy()
                undo[undo.index('add')] = 'del'
                self.undo.append(undo)
            # Docker's default FORWARD DROP needs a narrow positive permission.
            # The earlier nft guard still rejects OFF/expired/reverse traffic.
            forward=['iptables','-I','DOCKER-USER','1','-i',cfg.wg_interface,'-o',cfg.physical_interface,
                     '-s',cfg.home,'-d',candidate.network,'-m','comment','--comment','ha-node-c-business','-j','ACCEPT']
            reply=['iptables','-I','DOCKER-USER','1','-i',cfg.physical_interface,'-o',cfg.wg_interface,
                   '-s',candidate.network,'-d',cfg.home,'-m','conntrack','--ctstate','ESTABLISHED,RELATED',
                   '--ctdir','REPLY','--ctorigsrc',cfg.home,'-m','comment','--comment','ha-node-c-business','-j','ACCEPT']
            for command in (forward,reply):
                self.backend.run(command)
                undo=command.copy();undo[undo.index('-I')]='-D';del undo[3]
                self.undo.append(undo)
        except Exception:
            self.close()
            raise
