"""Offline policy model for the HA single-interface maintenance node.

No SSH, Docker, firewall or route mutations. Runtime adapters must enforce this
contract before they may be connected to the production controller.
"""
from dataclasses import dataclass
from ipaddress import IPv4Network, ip_address, ip_network
import hashlib
import json
import re

PRIVATE = tuple(ip_network(x) for x in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def private_network(value):
    n = ip_network(value, strict=True)
    if not isinstance(n, IPv4Network) or not 8 <= n.prefixlen <= 30:
        raise ValueError('canonical IPv4 LAN /8 through /30 required')
    if not any(n.subnet_of(p) for p in PRIVATE):
        raise ValueError('RFC1918 LAN required')
    return n


@dataclass(frozen=True)
class Candidate:
    network: str
    address: str
    gateway: str
    interface: str
    gateway_mac: str
    boot_id: str

    def validate(self, reserved):
        n = private_network(self.network)
        for value in (self.address, self.gateway):
            a = ip_address(value)
            if a not in n or a in (n.network_address, n.broadcast_address):
                raise ValueError('on-link unicast host required')
        if self.address == self.gateway:
            raise ValueError('node cannot be its own gateway')
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', self.interface):
            raise ValueError('invalid physical interface')
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', self.gateway_mac):
            raise ValueError('verified gateway MAC required')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', self.boot_id):
            raise ValueError('boot identity required')
        for r in reserved:
            if n.overlaps(ip_network(r, strict=True)):
                raise ValueError('customer LAN overlaps reserved network: ' + r)
        return self

    @property
    def fingerprint(self):
        # Binds authorization to address, link, gateway and this boot.
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True).encode()).hexdigest()


class BusinessGate:
    """Monotonic short lease, separate local consent and controller authority.

    Not persisted: process restart always returns to OFF. A local ON grants
    consent only. It never activates business without explicit controller ON.
    """
    def __init__(self, reserved, ttl=45):
        if not 1 <= ttl <= 45:
            raise ValueError('lease must be between 1 and 45 seconds')
        self.reserved = tuple(reserved)
        self.ttl = ttl
        self.local_consent = True
        self.close()

    def close(self):
        self.candidate = None
        self.expires = 0

    def local_set(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('boolean consent required')
        self.local_consent = enabled
        # Even local re-enable requires a fresh controller activation.
        self.close()

    def active(self, candidate, now):
        try:
            candidate.validate(self.reserved)
            valid = (self.local_consent and self.candidate is not None
                     and self.candidate.fingerprint == candidate.fingerprint
                     and 0 <= now < self.expires)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            self.close()
        return bool(valid)

    def activate(self, candidate, fingerprint, now):
        self.close()
        candidate.validate(self.reserved)
        if not self.local_consent or fingerprint != candidate.fingerprint or now < 0:
            raise ValueError('local consent or candidate authorization missing')
        self.candidate = candidate
        self.expires = now + self.ttl

    def renew(self, candidate, fingerprint, now):
        if fingerprint != candidate.fingerprint or not self.active(candidate, now):
            self.close()
            raise ValueError('lease lost; explicit controller activation required')
        self.expires = now + self.ttl

    def allow(self, candidate, now, *, direction, new_connection=False,
              reply_to_authorized=False, management=False):
        if management:
            # Caller must separately verify fixed management identity/ports.
            return direction == 'home_to_node' or (
                direction == 'node_to_home' and not new_connection and reply_to_authorized)
        if not self.active(candidate, now):
            return False
        if direction in ('home_to_customer', 'home_to_node'):
            return True
        if direction in ('customer_to_home', 'node_to_home'):
            return not new_connection and reply_to_authorized
        return False
