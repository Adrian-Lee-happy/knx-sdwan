import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get('BASH_BINARY') or shutil.which('bash')
if os.name == 'nt' and not os.environ.get('BASH_BINARY'):
    candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
    if candidate.is_file():
        BASH = str(candidate)


@unittest.skipUnless(BASH, 'Bash required for the actual shell IPv4 filter')
class PublicEndpointTests(unittest.TestCase):
    def allowed(self, value):
        library = ROOT / 'src/cudy/usr/lib/knx-wg-public-ip.sh'
        result = subprocess.run([BASH, '-c', '. "$1"; knx_public_ipv4 "$2"',
                                 'ipv4-test', str(library), value], capture_output=True, text=True, timeout=5)
        return result.returncode == 0

    def test_public_provider_addresses(self):
        for ip in ('1.1.1.1', '1.0.0.1', '223.5.5.5', '223.6.6.6'):
            self.assertTrue(self.allowed(ip))

    def test_private_fake_ip_and_special_purpose(self):
        vectors = [
            (0, 1, 1, 1), (10, 61, 1, 42), (127, 0, 0, 1),
            (100, 64, 0, 1), (100, 127, 255, 254), (169, 254, 1, 1),
            (172, 16, 0, 1), (172, 31, 255, 254), (192, 168, 0, 1),
            (192, 0, 0, 1), (192, 0, 2, 1), (192, 88, 99, 1),
            (198, 18, 0, 1), (198, 19, 255, 254), (198, 51, 100, 1),
            (203, 0, 113, 1), (224, 0, 0, 1), (255, 255, 255, 255),
        ]
        for vector in vectors:
            self.assertFalse(self.allowed('.'.join(map(str, vector))))

    def test_malformed_values(self):
        for value in ('', 'localhost', '0' + '1.1.1.1', '1.1.1', '1.1.1.1/32',
                      '1.1.1.1;false', '.'.join(['1', '1', '1', '999'])):
            self.assertFalse(self.allowed(value))


if __name__ == '__main__':
    unittest.main()
