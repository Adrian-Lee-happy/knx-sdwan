import sys
from pathlib import Path as _Path
sys.path.insert(0,str(_Path(__file__).resolve().parents[1]/'src/ha_node'))
import json
from dataclasses import replace
from types import SimpleNamespace
import unittest

from linux_backend import Config, Backend, firewall, OWNER
from node_policy import Candidate


class FakeRunner:
    def __init__(self, owner=OWNER):
        self.calls=[]; self.owner=owner

    def __call__(self, argv, text=None, check=True):
        self.calls.append((argv,text))
        if argv[:3] == ['nft','-j','list']:
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'nftables':[{'table':{'comment':self.owner}}]}))
        return SimpleNamespace(returncode=0, stderr='', stdout='')


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.cfg=Config('10.60.0.0/24','10.62.0.13','10.62.0.1')
        self.c=Candidate('10.63.1.0/24','10.63.1.2','10.63.1.1',
                         'end0','02:11:22:33:44:55','11111111-2222-3333-4444-555555555555')

    def test_foreign_table_is_never_replaced(self):
        runner=FakeRunner('other-product')
        with self.assertRaises(RuntimeError):Backend(self.cfg,runner).install_off()
        self.assertEqual(len(runner.calls),1)

    def test_install_checks_before_applying(self):
        runner=FakeRunner();Backend(self.cfg,runner).install_off()
        self.assertEqual(runner.calls[1][0],['nft','-c','-f','-'])
        self.assertEqual(runner.calls[1][1],runner.calls[2][1])
        self.assertNotIn('flush ruleset',runner.calls[2][1])

    def test_ipv6_and_unsolicited_reverse_have_final_drop(self):
        text=firewall(self.cfg)
        self.assertIn('oifname "wg_ha" meta nfproto ipv6 drop',text)
        self.assertIn('ct original ip saddr 10.60.0.0/24',text)
        self.assertIn('oifname "wg_ha" drop',text)
        self.assertNotIn('ct state established,related accept',text)

    def test_invalid_activation_first_closes_business(self):
        runner=FakeRunner();b=Backend(self.cfg,runner)
        c=replace(self.c,network='10.60.0.0/24',address='10.60.0.20',gateway='10.60.0.1')
        with self.assertRaises(ValueError):b.open(c)
        self.assertEqual(len(runner.calls),2)
        self.assertIn('flush set inet ha_remote_node lease',runner.calls[1][1])

    def test_open_only_uses_expiring_kernel_permission(self):
        runner=FakeRunner();Backend(self.cfg,runner).open(self.c)
        text=runner.calls[-1][1]
        self.assertIn('timeout 45s',text)
        self.assertIn(self.c.network,text)

    def test_route_plan_does_not_replace_main_default(self):
        plan=Backend(self.cfg).route_plan(self.c)
        self.assertTrue(all('replace' not in p for p in plan))
        self.assertTrue(all('21890' in p for p in plan))
        self.assertEqual(plan[-1][-2:],['lookup','21890'])

    def test_deleted_kernel_lease_cannot_be_renewed(self):
        runner=FakeRunner()
        def missing(argv,text=None,check=True):
            if argv[:3]==['nft','get','element']:
                return SimpleNamespace(returncode=1,stderr='No such file',stdout='')
            return runner(argv,text,check)
        with self.assertRaises(RuntimeError):Backend(self.cfg,missing).renew()
        self.assertFalse(any('flush set' in (text or '') for _,text in runner.calls))

    def test_interface_injection_and_reserved_priorities_fail(self):
        for cfg in (replace(self.cfg,wg_interface='wg;reboot'),replace(self.cfg,route_table=254),
                    replace(self.cfg,rule_priority=1700),replace(self.cfg,agent_port=22)):
            with self.assertRaises(ValueError):cfg.validate()


if __name__=='__main__':unittest.main()
