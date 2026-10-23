local M={}
M.json=require'luci.jsonc'; M.n=require'nixio'; require'nixio.util'; M.fs=require'nixio.fs'
function M.read(p,default) local s=M.fs.readfile(p);return s and M.json.parse(s) or default end
function M.write(p,v) local f=assert(M.n.open(p..'.tmp','w','600'));assert(f:writeall(M.json.stringify(v)));f:close();assert(M.fs.rename(p..'.tmp',p)) end
function M.run(program,args,input,seconds)
 local r,w=assert(M.n.pipe());local ir,iw=assert(M.n.pipe());local pid=assert(M.n.fork())
 if pid==0 then
  assert(M.n.setsid())
  r:close();iw:close();M.n.dup(ir,M.n.stdin);M.n.dup(w,M.n.stdout);M.n.dup(w,M.n.stderr);ir:close();w:close()
  M.n.exec(program,unpack(args or {}));os.exit(127)
 end
 ir:close();w:close()
 local timer=assert(M.n.fork())
 if timer==0 then
  r:close();iw:close();M.n.nanosleep(seconds or 15);M.n.kill(-pid,15);M.n.nanosleep(1);M.n.kill(-pid,9);os.exit(0)
 end
 if input then iw:writeall(input) end;iw:close()
 local text=r:readall() or '';r:close();local _,kind,code=M.n.waitpid(pid)
 M.n.kill(timer,9);M.n.waitpid(timer)
 return kind=='exited' and code or 128,text
end
function M.must(program,args,input) local rc,out=M.run(program,args,input);assert(rc==0,'command failed: '..program);return out end
function M.nft(text) return M.must('/usr/sbin/nft',{'-f','-'},text..'\n') end
function M.ip(args,ignore) local rc,out=M.run('/sbin/ip',args);if not ignore then assert(rc==0,'route operation failed') end;return out end
function M.uci(s) local rc,v=M.run('/sbin/uci',{'-q','get',s});return rc==0 and v:match('^%s*(.-)%s*$') or nil end
function M.ipnum(s)
 if type(s)~='string' then return nil end
 local a,b,c,d=s:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$');if not a then return nil end
 local n=0;for _,v in ipairs({a,b,c,d})do if tonumber(v)>255 or (#v>1 and v:sub(1,1)=='0')then return nil end;n=n*256+tonumber(v)end;return n
end
function M.ipstr(n) local t={};for i=4,1,-1 do t[i]=tostring(n%256);n=math.floor(n/256) end;return table.concat(t,'.')end
function M.range(s)
 if type(s)~='string' then return nil end
 local ip,p=s:match('^([^/]+)/(%d+)$');p=tonumber(p);local n=M.ipnum(ip)
 if not n or not p or p>32 then return nil end
 local size=2^(32-p);local first=math.floor(n/size)*size
 return first,first+size-1,p,M.ipstr(first)..'/'..p
end
function M.overlap(a,b) local x,y=M.range(a);local u,v=M.range(b);return x and u and x<=v and u<=y or false end
function M.private(s)
 local a,b,p,canon=M.range(s);if not a or p<8 or p>30 or canon~=s then return false end
 for _,pool in ipairs({'10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'})do local x,y=M.range(pool);if a>=x and b<=y then return true end end;return false
end
function M.lock(path,nonblock) local f=assert(M.n.open(path,'w','600'));assert(f:lock(nonblock and 'tlock' or 'lock'),'busy');return f end
function M.has(set,value) local rc=M.run('/usr/sbin/nft',{'get','element','inet','fw4',set,'{ '..value..' }'});return rc==0 end
function M.ct(a,b)
 if not a or not b then return end
 local rc=M.run('/usr/sbin/conntrack',{'-D','-f','ipv4','-s',a,'-d',b})
 assert(rc==0 or rc==1,'conntrack cleanup failed')
end
return M
