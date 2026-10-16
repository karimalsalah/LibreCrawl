"""Refuse crawl targets on private, loopback, link-local and other non-public addresses.

A crawler that fetches whatever URL it is given (and whatever those pages link or
redirect to) can be pointed at the machine it runs on, the LAN behind it, or a cloud
metadata endpoint such as 169.254.169.254. The check runs on every request the
crawler's HTTP session sends, so redirects are covered too, and on every request the
JavaScript renderer's browser makes.

Set ALLOW_PRIVATE_TARGETS=true to turn the check off, for example to crawl a site
running on your own machine or LAN.
"""
import ipaddress
import os
import socket
from urllib.parse import urlsplit

import requests


class BlockedTarget(requests.exceptions.InvalidURL):
    """Raised when a URL resolves to an address the crawler must not reach."""


def private_targets_allowed():
    return os.getenv('ALLOW_PRIVATE_TARGETS', '').lower() in ('true', '1', 'yes')


def _is_public(address):
    ip = ipaddress.ip_address(address.split('%', 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def blocked_reason(url):
    """Return why `url` may not be fetched, or None when it may.

    Every address the host resolves to must be public; one private answer is enough
    to refuse, so a name with mixed records cannot be used to reach the inside.
    A host that does not resolve is left to the HTTP client to report.
    """
    if private_targets_allowed():
        return None
    host = urlsplit(url).hostname
    if not host:
        return None
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return None
    for info in infos:
        address = info[4][0]
        try:
            if not _is_public(address):
                return (f'{host} resolves to non-public address {address}; '
                        'set ALLOW_PRIVATE_TARGETS=true to crawl private networks')
        except ValueError:
            return f'{host} resolved to an unparseable address'
    return None


def check_url(url):
    reason = blocked_reason(url)
    if reason:
        raise BlockedTarget(reason)


class GuardedHTTPAdapter(requests.adapters.HTTPAdapter):
    """HTTPAdapter that checks each outgoing request, including every redirect hop."""

    def send(self, request, *args, **kwargs):
        check_url(request.url)
        return super().send(request, *args, **kwargs)
