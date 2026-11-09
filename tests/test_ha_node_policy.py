import sys
from pathlib import Path as _Path
sys.path.insert(0,str(_Path(__file__).resolve().parents[1]/'src/ha_node'))
from dataclasses import replace
import unittest
from node_policy import BusinessGate, Candidate


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.c = Candidate('10.63.1.0/24', '10.63.1.20',
                           '10.63.1.1', 'end0', '02:11:22:33:44:55',
                           '11111111-2222-3333-4444-555555555555')
        self.g = BusinessGate(['10.60.0.0/24', '10.62.0.0/24', '172.30.32.0/23'])

    def on(self):
        self.g.activate(self.c, self.c.fingerprint, 100)

    def test_current_home_network_refused(self):
        c = replace(self.c, network='10.60.0.0/24', address='10.60.0.20', gateway='10.60.0.1')
        with self.assertRaises(ValueError): self.g.activate(c, c.fingerprint, 100)
        self.assertFalse(self.g.active(self.c, 100))

    def test_reverse_new_connections_always_denied(self):
        self.on()
        for direction in ('customer_to_home', 'node_to_home'):
            self.assertFalse(self.g.allow(self.c, 101, direction=direction, new_connection=True))
            self.assertTrue(self.g.allow(self.c, 101, direction=direction, reply_to_authorized=True))
            self.assertFalse(self.g.allow(self.c, 101, direction=direction))

    def test_off_revokes_existing_replies(self):
        self.on(); self.g.close()
        self.assertFalse(self.g.allow(self.c, 101, direction='customer_to_home', reply_to_authorized=True))

    def test_expiry_cannot_be_revived_by_renew(self):
        self.on()
        with self.assertRaises(ValueError): self.g.renew(self.c, self.c.fingerprint, 145)
        self.assertFalse(self.g.active(self.c, 146))

    def test_gateway_address_or_boot_change_closes_business(self):
        for changes in ({'gateway_mac':'02:99:88:77:66:55'},
                        {'address':'10.63.1.21'},
                        {'boot_id':'99999999-2222-3333-4444-555555555555'}):
            self.on()
            self.assertFalse(self.g.active(replace(self.c, **changes), 101))
            self.assertFalse(self.g.active(self.c, 102))

    def test_local_on_does_not_bypass_controller(self):
        self.on(); self.g.local_set(False)
        with self.assertRaises(ValueError):self.g.activate(self.c, self.c.fingerprint, 101)
        self.g.local_set(True)
        self.assertFalse(self.g.active(self.c, 102))

    def test_management_survives_off_without_reverse_permission(self):
        self.assertTrue(self.g.allow(self.c, 100, direction='home_to_node', management=True))
        self.assertFalse(self.g.allow(self.c, 100, direction='node_to_home', new_connection=True, management=True))

    def test_invalid_activation_clears_old_authorization(self):
        self.on()
        with self.assertRaises(ValueError):self.g.activate(self.c, 'wrong', 101)
        self.assertFalse(self.g.active(self.c, 102))

    def test_overbroad_or_malformed_candidates_rejected(self):
        for changes in ({'network':'0.0.0.0/0'}, {'interface':'end0; reboot'},
                        {'gateway':'1.1.1.1'}, {'gateway_mac':'not-verified'}):
            with self.assertRaises(ValueError):replace(self.c, **changes).validate(self.g.reserved)

    def test_new_process_defaults_off(self):
        self.on()
        other=BusinessGate(self.g.reserved)
        self.assertFalse(other.active(self.c, 101))


if __name__ == '__main__':unittest.main()
