import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gateway_render', ROOT / 'tools/render.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
CONFIG = json.loads((ROOT / 'config/site.example.json').read_text(encoding='utf-8'))


class GatewayCompatibilityTests(unittest.TestCase):
    def test_listen_port_validation_and_legacy_default(self):
        legacy = dict(CONFIG)
        legacy.pop('client_listen_port')
        self.assertEqual(render.parameters(legacy)['CLIENT_LISTEN_PORT'], '51831')
        for bad in (True, 0, 65536, '51831;false'):
            with self.subTest(port=bad), self.assertRaises(ValueError):
                render.parameters(dict(CONFIG, client_listen_port=bad))

    def test_render_preserves_transport_callback_and_guard_contract(self):
        cfg = dict(CONFIG, client_listen_port=51832, physical_wan_device='wan')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'bundle'
            entries = render.render(cfg, out)
            for e in entries:
                self.assertNotIn(b'\r', (out / e['path']).read_bytes(), e['path'])
            network = (out / 'cudy/integration/network.uci').read_text()
            firewall = (out / 'cudy/integration/firewall.uci').read_text()
            self.assertIn("option listen_port '51832'", network)
            self.assertIn("option dest_port '51832'", firewall)
            self.assertIn("option src_port '51821'", firewall)
            self.assertIn("option path '/usr/sbin/knx-direct-reset'", firewall)
            reset = out / 'cudy/rootfs/usr/sbin/knx-direct-reset'
            self.assertTrue(reset.read_text().startswith('#!/bin/sh\n'))
            self.assertIn('exec /usr/sbin/knx-direct-agent reset', reset.read_text())
            guard = (out / 'cudy/rootfs/etc/nftables.d/90-knx-stage1.nft').read_text()
            self.assertIn('hook prerouting priority -190', guard)
            self.assertIn('iifname "br-lan" ip daddr 10.60.0.0/24 ip saddr != 10.61.1.0/24 counter drop', guard)
            self.assertIn('iifname != @knx_direct_lease counter drop', guard)
            self.assertIn('iifname "wg_home" counter drop', guard)
            dropbear = (out / 'cudy/integration/dropbear.uci').read_text()
            self.assertEqual(dropbear.count("option PasswordAuth 'off'"), 2)
            self.assertEqual(dropbear.count("option RootPasswordAuth 'off'"), 2)
            delta = (out / 'r86s/integration/additional-customer.uci').read_text()
            self.assertNotIn("config interface 'wg_customers'", delta)
            self.assertIn("list allowed_ips '10.62.0.11/32'", delta)
            self.assertIn("option route_allowed_ips '0'", delta)


if __name__ == '__main__':
    unittest.main()
