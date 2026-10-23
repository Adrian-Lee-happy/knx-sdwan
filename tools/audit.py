#!/usr/bin/env python3
"""Local-only release allowlist/content audit. Never prints matching secrets."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', '.gitattributes', 'README.md', 'SOURCE-MANIFEST.json', 'RELEASE-FILES.txt'}
PREFIXES = ('src/', 'integration/', 'config/', 'docs/', 'tools/', 'tests/')
SAFE_IPS = {
    '0.0.0.0', '10.0.0.0', '172.16.0.0', '192.168.0.0',
    '1.1.1.1', '1.0.0.1', '223.5.5.5', '223.6.6.6',
}
EXAMPLE_POOLS = tuple(ipaddress.ip_network(s) for s in ('10.60.0.0/24', '10.61.1.0/24', '10.62.0.0/24'))
RULES = {
    'private-key-header': re.compile(r'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----'),
    'wg-key-shaped-value': re.compile(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/=])'),
    'ssh-identity': re.compile(r'\bssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/=]{60,}'),
    'github-credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'credential-in-url': re.compile(r'https?://[^\s/]+:[^\s/@]+@'),
    'windows-user-path': re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+', re.I),
}


def audit(root=ROOT):
    errors, records = [], []
    listed_path = root / 'RELEASE-FILES.txt'
    if not listed_path.is_file():
        return ['missing release file allowlist'], []
    listed = listed_path.read_text(encoding='utf-8').splitlines()
    if listed != sorted(set(listed)):
        errors.append('release file allowlist must be sorted and unique')
    actual = []
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        if p.relative_to(root).parts[0] == '.git':
            continue
        if '.git' in p.relative_to(root).parts:
            errors.append(rel + ': nested Git metadata forbidden')
            continue
        if p.is_symlink():
            errors.append(rel + ': symlink forbidden')
            continue
        if not p.is_file():
            continue
        actual.append(rel)
        if rel not in ROOT_FILES and not rel.startswith(PREFIXES):
            errors.append(rel + ': unapproved path')
        if rel.startswith('config/') and rel != 'config/site.example.json':
            errors.append(rel + ': real configuration forbidden')
        if p.suffix.lower() in {'.zip', '.tgz', '.gz', '.tar', '.key', '.pem', '.log', '.pcap', '.bak', '.pyc'}:
            errors.append(rel + ': forbidden artifact')
        if p.name.lower() in {'authorized_keys', 'known_hosts', '.env'} or p.name.startswith('id_'):
            errors.append(rel + ': forbidden credential path')
        raw = p.read_bytes()
        if len(raw) > 300_000 or b'\x00' in raw:
            errors.append(rel + ': oversized or binary file')
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            errors.append(rel + ': non-UTF8 content')
            continue
        for name, pattern in RULES.items():
            if pattern.search(text):
                errors.append(rel + ': ' + name)
        for literal in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', text):
            try:
                a = ipaddress.IPv4Address(literal)
            except ValueError:
                errors.append(rel + ': malformed IPv4 literal')
                continue
            if literal not in SAFE_IPS and not any(a in pool for pool in EXAMPLE_POOLS):
                errors.append(rel + ': unapproved IPv4 literal (value omitted)')
        for host in re.findall(r'https?://([A-Za-z0-9.-]+)', text):
            if host not in {'github.com', 'cloudflare-dns.com', 'dns.alidns.com'} and not host.endswith('.invalid'):
                errors.append(rel + ': unapproved URL host (value omitted)')
        if re.search(r'https?' + r'://github[.]com/(?:settings/tokens|login/device[?])', text):
            errors.append(rel + ': authentication artifact')
        records.append({'path': rel, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    if set(actual) != set(listed):
        errors.append('actual file tree differs from reviewed release allowlist')
    provenance = json.loads((root / 'SOURCE-MANIFEST.json').read_text(encoding='utf-8'))
    for entry in provenance['entries']:
        p = root / entry['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != entry['publication_sha256']:
            errors.append(entry['path'] + ': publication provenance hash mismatch')
    return sorted(set(errors)), records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Optional report OUTSIDE the repository')
    args = parser.parse_args()
    if args.report:
        dest = args.report.resolve()
        if dest == ROOT or ROOT in dest.parents:
            parser.error('Audit report must remain outside the repository')
    failures, inventory = audit()
    if args.report:
        args.report.write_text(json.dumps({'pass': not failures, 'errors': failures, 'files': inventory}, indent=2) + '\n', encoding='utf-8')
    for problem in failures:
        print('FAIL:', problem)
    print('Release allowlist/content audit: %s; %d UTF-8 files reviewed' % ('FAIL' if failures else 'PASS', len(inventory)))
    raise SystemExit(bool(failures))
