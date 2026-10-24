import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('render', ROOT / 'tools/render.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
CONFIG = json.loads((ROOT / 'config/site.example.json').read_text(encoding='utf-8'))

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None


class TemplateTests(unittest.TestCase):
    def test_valid_example(self):
        self.assertEqual(render.parameters(CONFIG)['WG_PREFIX'], '24')

    def test_overlap_and_injection_refused(self):
        cases = [
            ('private_lan_cidr', CONFIG['home_cidr']),
            ('physical_wan_device', 'eth0;false'),
            ('server_peer_section', '../../escape'),
            ('endpoint_host', "bad.invalid';false"),
            ('endpoint_host', '10.60.0.1'),
            ('client_wg_ip', CONFIG['server_wg_ip']),
            ('home_router_ip', 171704321),
            ('wg_port', True),
            ('wg_port', 65536),
            ('openclash_compat_enabled', 'yes'),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                cfg = copy.deepcopy(CONFIG)
                cfg[field] = value
                with self.assertRaises(ValueError):
                    render.parameters(cfg)

    def test_unknown_field_refused(self):
        cfg = dict(CONFIG, extra='not accepted')
        with self.assertRaises(ValueError):
            render.parameters(cfg)

    def test_output_cannot_overwrite_or_enter_repository(self):
        with self.assertRaises(ValueError):
            render.render(CONFIG, ROOT / 'build')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                render.render(CONFIG, d)

    def test_render_and_closed_default(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'new'
            files = render.render(CONFIG, out)
            self.assertGreater(len(files), 30)
            self.assertEqual((out / 'r86s/rootfs/etc/knx-customers/a-state').read_text().strip(), 'off')
            self.assertNotIn('elements', (out / 'r86s/rootfs/etc/knx-customers/a-gate.nft').read_text())
            self.assertFalse((out / 'r86s/rootfs/etc/hotplug.d/iface/95-knx-policy').exists())
            agent = (out / 'cudy/rootfs/usr/sbin/knx-direct-agent').read_text(encoding='utf-8')
            self.assertIn("~='10.62.0.1'", agent)
            self.assertIn('physical WAN has no active DHCP lease', agent)
            for entry in files:
                text = (out / entry['path']).read_text(encoding='utf-8')
                self.assertNotRegex(text, r'@[A-Z][A-Z0-9_]*@')

    def test_explicit_compatibility_hook(self):
        cfg = dict(CONFIG, openclash_compat_enabled=True)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'new'
            render.render(cfg, out)
            hook = out / 'r86s/rootfs/etc/hotplug.d/iface/95-knx-policy'
            self.assertTrue(hook.is_file())


@unittest.skipUnless(LuaRuntime, 'Install lupa with lua51 support outside the repository')
class LuaLogicTests(unittest.TestCase):
    def runtime(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute("""
            package.preload['luci.jsonc']=function()return{}end
            package.preload['nixio']=function()return{}end
            package.preload['nixio.util']=function()return{}end
            package.preload['nixio.fs']=function()return{}end
        """)
        return lua

    def test_real_library_ip_and_overlap(self):
        lua = self.runtime()
        d = lua.execute((ROOT / 'src/common/usr/lib/knx-direct.lua').read_text(encoding='utf-8'))
        for value in ('0' + '10.60.0.1', '.'.join(['256', '1', '1', '1']), '10.60.0', '10.60.0.1;false', ''):
            self.assertIsNone(d.ipnum(value))
        self.assertEqual(d.ipstr(d.ipnum('10.60.0.1')), '10.60.0.1')
        self.assertTrue(d.private('10.60.0.0/24'))
        self.assertFalse(d.private('10.60.0.1/24'))
        self.assertTrue(d.overlap('10.60.0.0/24', '10.60.0.1/32'))
        self.assertFalse(d.overlap('10.60.0.0/24', '10.61.1.0/24'))

    def test_actual_uplink_state_machine(self):
        lua = self.runtime()
        text = (ROOT / 'src/cudy/usr/sbin/knx-uplink.in').read_text(encoding='utf-8')
        start = text.index('local function transition(')
        end = text.index("\nif action=='selftest'", start)
        transition = lua.execute(text[start:end] + '\nreturn transition')
        s = lua.table()
        transition(s, True, 100, True)
        self.assertFalse(s.active)
        transition(s, True, 130, True)
        self.assertTrue(s.active)
        transition(s, False, 160, True)
        self.assertTrue(s.active)
        transition(s, False, 190, True)
        self.assertFalse(s.active)
        transition(s, True, 220, True)
        self.assertFalse(s.active)
        transition(s, True, 250, True)
        self.assertTrue(s.active)
        transition(s, True, 251, False)
        self.assertFalse(s.active)

    def test_only_throw_routes_bypass_route_conflict_check(self):
        import re
        lua = self.runtime()
        d = lua.execute((ROOT / 'src/common/usr/lib/knx-direct.lua').read_text(encoding='utf-8'))
        lua.globals().TEST_D = d
        lua.execute("""
            TEST_D.run=function(program,args)
                if program=='/sbin/ip' then return 0,'ROUTES' end
                return 1,''
            end
            TEST_D.json.parse=function()return TEST_ROUTES end
            package.preload['uci']=function()return {cursor=function()return {foreach=function()end}end}end
        """)
        source = (ROOT / 'src/r86s/usr/sbin/knx-direct-controller.in').read_text(encoding='utf-8')
        values = render.parameters(CONFIG)
        source = re.sub(r'@([A-Z][A-Z0-9_]*)@', lambda m: values[m[1]], source)
        section = source[source.index('local function conflict('):source.index('local function known(')]
        check = lua.execute("""
            local D=TEST_D
            local clients={a={lan='10.61.1.0/24',tunnel='10.62.0.11'}}
            local HOME='10.61.1.0/24'
            local function pub()return 'fixture-only'end
        """ + section + '\nreturn conflict')
        customer = lua.table()
        for route_type in ('throw', 'unicast', 'blackhole', 'unreachable', 'prohibit', None, 'unknown'):
            with self.subTest(route_type=route_type):
                route = lua.table_from({'dst': '10.0.0.0/8', 'table': 354})
                if route_type is not None:
                    route.type = route_type
                lua.globals().TEST_ROUTES = lua.table_from([route])
                result = check(customer, '10.60.0.0/24')
                if route_type == 'throw':
                    self.assertIsNone(result)
                else:
                    self.assertIn('overlaps an existing route', result)
        lua.globals().TEST_ROUTES = lua.table_from([
            lua.table_from({'type': 'throw', 'dst': '10.0.0.0/8', 'table': 354}),
            lua.table_from({'type': 'unicast', 'dst': '10.60.0.0/24', 'table': 'main'}),
        ])
        self.assertIn('overlaps an existing route', check(customer, '10.60.0.0/24'))

    def test_agent_no_wan_and_query_failure_refuse_activation(self):
        text = (ROOT / 'src/cudy/usr/sbin/knx-direct-agent.in').read_text(encoding='utf-8').split('\n', 1)[1]
        values = render.parameters(CONFIG)
        import re
        text = re.sub(r'@([A-Z][A-Z0-9_]*)@', lambda m: values[m[1]], text)
        for method in ('probe', 'activate'):
            for rc in (0, 1):
                with self.subTest(method=method, query_rc=rc):
                    lua = self.runtime()
                    lua.globals().TEST_METHOD = method
                    lua.globals().TEST_QUERY_RC = rc
                    lua.execute("""
                        local D={}
                        D.read=function(p) if p:match('agent.json$') then return {physical_device='eth0',lan='10.61.1.0/24'} end;return {} end
                        D.fs={mkdir=function()end}
                        D.run=function()return TEST_QUERY_RC,'WAN_DOWN'end
                        D.json={parse=function()return {up=false}end,stringify=function(v)return v end}
                        D.lock=function()return {close=function()end}end
                        D.ip=function()return ''end
                        D.ct=function()end
                        D.write=function()end
                        D.private=function()return false end
                        dofile=function()return D end
                        os.getenv=function(k) if k=='SSH_ORIGINAL_COMMAND' then return TEST_METHOD elseif k=='SSH_CONNECTION' then return '10.62.0.1 10000 10.62.0.11 22' end end
                        os.exit=function(code)TEST_EXIT=code end
                        io.read=function()return '{}'end
                        print=function(v)TEST_RESULT=v end
                    """)
                    lua.execute(text)
                    result = lua.globals().TEST_RESULT
                    if method == 'probe':
                        self.assertTrue(result.success)
                        self.assertFalse(result.candidate.valid)
                        self.assertFalse(result.active)
                    else:
                        self.assertFalse(result.success)
                        self.assertEqual(lua.globals().TEST_EXIT, 1)


if __name__ == '__main__':
    unittest.main()
