"""Root-only Unix RPC behind key-authenticated SSH; loopback consent API."""
import hmac
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import signal

from agent_runtime import Agent, Routes
from linux_backend import Config, Backend, discover

STATE = Path('/state')
SOCKET = '/run/ha-remote/agent.sock'


def relay():
    method = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    source = os.environ.get('SSH_CONNECTION', '').split()
    if method not in Agent.METHODS or not source:
        raise SystemExit(1)
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise SystemExit(1)
    request = {'method': method, 'source': source[0], 'payload': json.loads(raw or b'{}')}
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(8)
        s.connect(SOCKET)
        s.sendall(json.dumps(request).encode() + b'\n')
        s.shutdown(socket.SHUT_WR)
        response = s.recv(16384)
    print(response.decode())
    raise SystemExit(0 if json.loads(response).get('success') else 1)


def serve():
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: stopping.set())
    data = json.loads((STATE / 'config.json').read_text())
    cfg = Config(**data['network']).validate()
    backend = Backend(cfg)
    backend.install_off()
    routes = Routes(backend)
    # Management bootstrap must have created the tunnel and its precise routes.
    agent = Agent(cfg, backend, routes, lambda: discover(cfg))
    consent_file = STATE / 'consent.json'
    if consent_file.exists():
        value = json.loads(consent_file.read_text())['enabled']
        if not isinstance(value, bool):raise ValueError('invalid stored consent')
        agent.gate.local_consent = value
    secret = (STATE / 'consent_token').read_text().strip()
    if len(secret) < 40:raise ValueError('consent secret too short')
    lock = threading.Lock()
    def refresh_endpoint():
        # Raw wg does not create a stale host route for the public endpoint.
        # Failed refresh keeps the last address; it never changes authorization.
        from bootstrap import endpoint
        while True:
            time.sleep(300)
            try:
                address=endpoint(data['endpoint_host'])
                subprocess.run(['wg','set',cfg.wg_interface,'peer',data['server_public_key'],
                                'endpoint',address+':'+str(data['endpoint_port'])],
                               check=True,capture_output=True,timeout=8)
            except Exception:
                pass
    threading.Thread(target=refresh_endpoint,daemon=True).start()

    class Consent(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):pass
        def respond(self, code, data):
            body=json.dumps(data).encode()
            self.send_response(code);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def authorized(self):
            return self.path == '/consent' and hmac.compare_digest(
                self.headers.get('Authorization',''), 'Bearer '+secret)
        def do_GET(self):
            if not self.authorized():return self.respond(403,{'error':'denied'})
            with lock:
                active=False
                if agent.gate.candidate is not None:
                    try:
                        active=agent.gate.active(agent.candidate(),agent.clock())
                        if not active:agent.close()
                    except Exception:agent.close()
                self.respond(200,{'enabled':agent.gate.local_consent,'business':active})
        def do_POST(self):
            if not self.authorized():return self.respond(403,{'error':'denied'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 128:raise ValueError()
                value=json.loads(self.rfile.read(length))
                if set(value) != {'enabled'} or not isinstance(value['enabled'],bool):raise ValueError()
                with lock:
                    agent.local_set(value['enabled'])
                    tmp=consent_file.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.chmod(0o600);tmp.replace(consent_file)
                    self.respond(200,{'enabled':value['enabled'],'business':False})
            except Exception:self.respond(400,{'error':'operation failed'})

    web_server = http.server.HTTPServer(('127.0.0.1',8766),Consent)
    web_server.timeout=5
    threading.Thread(target=web_server.serve_forever,daemon=True).start()
    Path('/run/ha-remote').mkdir(mode=0o700,exist_ok=True)
    Path(SOCKET).unlink(missing_ok=True)
    sshd=subprocess.Popen(['/usr/sbin/sshd','-D','-e','-f','/state/sshd_config'])
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(SOCKET);os.chmod(SOCKET,0o600);listener.listen(4);listener.settimeout(1)
        try:
            while not stopping.is_set() and sshd.poll() is None:
                try:
                    conn,_=listener.accept()
                    with conn:
                        conn.settimeout(3);raw=b''
                        while len(raw)<=8192:
                            chunk=conn.recv(8193-len(raw))
                            if not chunk:break
                            raw+=chunk
                            if b'\n' in raw:break
                        if len(raw)>8192:raise ValueError('request too large')
                        req=json.loads(raw)
                        with lock:result=agent.handle(req.get('method'),req.get('payload'),source=req.get('source'))
                        conn.sendall(json.dumps(result).encode())
                except socket.timeout:pass
                except (ValueError,OSError):pass
                with lock:agent.tick()
        finally:
            web_server.shutdown();sshd.terminate()
            try:
                with lock:agent.close()
            finally:
                try:sshd.wait(timeout=3)
                except subprocess.TimeoutExpired:sshd.kill();sshd.wait()


if __name__=='__main__':
    relay() if sys.argv[1:] == ['relay'] else serve()
