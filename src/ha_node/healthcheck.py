"""No secrets in health output; the endpoint is bound to host loopback."""
import json
from pathlib import Path
import urllib.request

token=Path('/state/consent_token').read_text().strip()
request=urllib.request.Request('http://127.0.0.1:8766/consent',
                               headers={'Authorization':'Bearer '+token})
with urllib.request.urlopen(request,timeout=4) as response:
    data=json.load(response)
if not isinstance(data.get('enabled'),bool) or not isinstance(data.get('business'),bool):
    raise SystemExit(1)
