import sys
from pathlib import Path as _Path
sys.path.insert(0,str(_Path(__file__).resolve().parents[1]/'src/ha_node'))
"""Execute controller Lua with deterministic OS stubs, not text assertions."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]


class ControllerTests(unittest.TestCase):
    def execute(self, action, owner=None, legacy=False):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().ACTION=action;lua.globals().OWNER=owner;lua.globals().LEGACY=legacy
        lua.execute('''
          commands={};writes={};exit_code=nil
          local function record(x)table.insert(commands,x)end
          local file={writeall=function()return true end,write=function()end,close=function()end}
          D={n={open=function()return file end,setenv=function()end},
             fs={rename=function()return true end,readfile=function(p)if p:find('-state')then return'off'else return nil end end},
             json={stringify=function()return '{}'end},
             ipnum=function(s)return type(s)=='string' and 1 or nil end,
             private=function(s)return type(s)=='string' and s:find('/')~=nil end,
             overlap=function(a,b)return a=='10.62.0.13/32' and b=='10.62.0.0/24' or a==b end,
             ct=function()end,lock=function()return file end,has=function()return true end}
          local c={id='c',peer='knx_customer_c',tunnel='10.62.0.13',profile='linux-ha-oneway',agent_port=22223,agent_key='/etc/knx-direct/c_id_ed25519'}
          if LEGACY then c.profile=nil;c.lan='10.61.1.0/24';c.agent_port=nil;c.agent_key=nil end
          local active=OWNER and {id=OWNER,network='10.63.1.0/24'} or {}
          D.read=function(p,default)
           if p:find('clients.json')then return {c=c}end
           if p:find('active.json')then return active end
           return default
          end
          D.write=function(p,v)writes[p]=v;if p:find('active.json')then active=v end end
          D.uci=function(p)if p:find('public_key')then return'PUB'elseif p:find('disabled')then return'0'end end
          D.ip=function(args)record('ip '..table.concat(args,' '));return '' end
          D.nft=function(t)record('nft '..t)end
          D.json.parse=function(s)
           if s=='REPORT'then return {success=true,active=true,candidate={valid=true,network='10.63.1.0/24',fingerprint=string.rep('a',64)}}end
           return {}
          end
          D.run=function(p,args)
           record(p..' '..table.concat(args or {},' '))
           if p=='/usr/bin/dbclient'then return 0,'REPORT'end
           if p=='/usr/bin/wg' and args[3]=='peers'then return 0,'PUB'end
           return 0,''
          end
          D.must=function(p,args)D.run(p,args);return ''end
          package.preload['uci']=function()return {cursor=function()return {foreach=function()end}end}end
          dofile=function()return D end
          arg={'c',ACTION};os.exit=function(c)exit_code=c end
          io.stderr={write=function(_,s)record('ERROR '..s)end}
          print=function()end
        ''')
        s=(ROOT/'src/r86s/usr/sbin/knx-direct-controller.in').read_text()
        for key,value in {'HOME_CIDR':'10.60.0.0/24','WG_CIDR':'10.62.0.0/24','SERVER_WG_IP':'10.62.0.1'}.items():s=s.replace('@'+key+'@',value)
        lua.execute(s.split('\n',1)[1])
        commands=list(lua.globals().commands.values())
        return lua.globals().exit_code,commands

    def test_c_off_does_not_flush_another_owner(self):
        code,commands=self.execute('off','a')
        self.assertEqual(code,0)
        self.assertFalse(any('flush set inet fw4 knx_direct_lease' in c for c in commands))
        self.assertFalse(any('rule del' in c for c in commands))

    def test_c_on_rejected_without_disabling_other_owner(self):
        code,commands=self.execute('on','b')
        self.assertEqual(code,1)
        self.assertFalse(any('flush set inet fw4 knx_direct_lease' in c for c in commands))
        self.assertFalse(any('activate' in c and 'deactivate' not in c for c in commands))

    def test_c_on_uses_no_fake_private_lan(self):
        code,commands=self.execute('on')
        self.assertEqual(code,0)
        self.assertFalse(any('pref 1709' in c for c in commands))
        self.assertTrue(any('pref 1710' in c for c in commands))
        self.assertTrue(any('-p 22223' in c for c in commands))
        self.assertTrue(any('c_id_ed25519' in c for c in commands))

    def test_legacy_node_still_uses_private_lan_and_default_transport(self):
        code,commands=self.execute('on',legacy=True)
        self.assertEqual(code,0)
        self.assertTrue(any('pref 1709' in c for c in commands))
        self.assertTrue(any('10.61.1.0/24' in c and 'knx_direct_lan' in c for c in commands))
        self.assertFalse(any('-p 22223' in c for c in commands))


if __name__=='__main__':unittest.main()
