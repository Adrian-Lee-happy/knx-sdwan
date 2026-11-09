import sys
from pathlib import Path as _Path
sys.path.insert(0,str(_Path(__file__).resolve().parents[1]/'src/ha_node'))
from dataclasses import replace
import unittest
from agent_runtime import Agent
from linux_backend import Config
from node_policy import Candidate


class Sink:
    def __init__(self, events, label):self.events=events;self.label=label;self.fail=False
    def close(self):self.events.append(self.label+'-off')
    def open(self,c):
        self.events.append(self.label+'-on')
        if self.fail:raise RuntimeError('private error detail')
    def renew(self):self.events.append(self.label+'-renew')


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.cfg=Config('10.60.0.0/24','10.62.0.13','10.62.0.1')
        self.c=Candidate('10.63.1.0/24','10.63.1.2','10.63.1.1','end0',
                         '02:11:22:33:44:55','11111111-2222-3333-4444-555555555555')
        self.events=[];self.now=100
        self.b=Sink(self.events,'firewall');self.r=Sink(self.events,'routes')
        self.agent=Agent(self.cfg,self.b,self.r,lambda:self.c,lambda:self.now)

    def request(self,m,p=None):
        return self.agent.handle(m,p or {},source=self.cfg.server)

    def activate(self):
        return self.request('activate',{'fingerprint':self.c.fingerprint})

    def test_controller_protocol_probe_and_activation(self):
        probe=self.request('probe');self.assertTrue(probe['candidate']['valid'])
        self.assertFalse(probe['active']);self.assertTrue(self.activate()['active'])

    def test_failure_closes_firewall_before_route_rollback(self):
        self.b.fail=True;r=self.activate()
        self.assertFalse(r['success']);self.assertNotIn('private',str(r))
        self.assertEqual(self.events[-2:],['firewall-off','routes-off'])

    def test_late_renew_cannot_reopen(self):
        self.activate();self.now=146
        self.assertFalse(self.request('renew',{'fingerprint':self.c.fingerprint})['success'])
        self.assertEqual(self.events[-2:],['firewall-off','routes-off'])

    def test_changed_network_requires_explicit_new_on(self):
        self.activate();self.c=replace(self.c,address='10.63.1.3');self.agent.tick()
        self.assertFalse(self.request('probe')['active'])

    def test_wrong_source_cannot_activate_or_disable(self):
        for method in ('activate','deactivate','probe'):
            self.assertFalse(self.agent.handle(method,{},source='10.62.0.99')['success'])
        self.assertEqual(self.events,[])

    def test_shell_method_and_unexpected_payload_rejected(self):
        self.assertFalse(self.request('sh -c reboot')['success'])
        self.assertFalse(self.request('activate',{'command':'reboot'})['success'])

    def test_local_reenable_only_grants_consent(self):
        self.activate();self.agent.local_set(False);self.agent.local_set(True)
        self.assertFalse(self.request('probe')['active'])


if __name__=='__main__':unittest.main()
