"""Process-wide IPv4 preference for hosts whose IPv6 route is broken (e.g. the college server).

Python libraries resolve both address families and try IPv6 first; on a network that advertises IPv6 but
cannot route it, every new connection waits for a timeout before falling back. Our own HTTP and websocket
clients force IPv4 directly, but third-party downloads (Hugging Face models, yfinance) do not, so when
TRIPWIRE_FORCE_IPV4 is set we restrict name resolution to IPv4 for the whole process.
"""

import socket

_original_getaddrinfo = socket.getaddrinfo
_applied = False


def prefer_ipv4() -> None:
    global _applied
    if _applied:
        return

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002 - mirrors socket API
        if family in (0, socket.AF_UNSPEC):
            family = socket.AF_INET
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = getaddrinfo
    _applied = True
