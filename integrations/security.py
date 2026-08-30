import ipaddress
import socket
from urllib.parse import urlparse

def validate_local_url(value: str) -> str:
    parsed=urlparse(value)
    if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("A valid HTTP(S) URL without embedded credentials is required")
    host=parsed.hostname.lower()
    if host in ("localhost","127.0.0.1","::1"): return value.rstrip("/")
    try:
        addresses={item[4][0] for item in socket.getaddrinfo(host,parsed.port or 80)}
    except socket.gaierror as error: raise ValueError("Endpoint hostname could not be resolved") from error
    if not addresses or any(not (ipaddress.ip_address(address).is_private or ipaddress.ip_address(address).is_loopback) for address in addresses):
        raise ValueError("Milestone 6 only connects to localhost or private-network endpoints")
    return value.rstrip("/")
