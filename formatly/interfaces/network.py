"""Shared binding and access addresses for the workbench and dev launcher."""
from __future__ import annotations

from ipaddress import IPv4Address
import socket

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


def normalize_bind_host(value: str) -> str:
    value = value.strip().lower()
    if value == "localhost":
        return value
    try:
        address = IPv4Address(value)
    except ValueError as exc:
        raise ValueError("监听地址须为 localhost 或 IPv4 地址") from exc
    if address.is_multicast or str(address) == "255.255.255.255":
        raise ValueError("不能使用组播或广播地址监听服务")
    return str(address)


def parse_port(value: str | int) -> int:
    try:
        port = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("端口须为 1–65535 的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("端口须为 1–65535 的整数")
    return port


def local_ipv4_addresses() -> tuple[str, ...]:
    """Discover local interface addresses without contacting an external service."""
    addresses: set[str] = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = IPv4Address(entry[4][0])
            if not (address.is_loopback or address.is_unspecified or address.is_multicast):
                addresses.add(str(address))
    except OSError:
        pass
    # UDP connect selects a local route without sending a packet. This also
    # works when /etc/hosts maps the machine name only to a loopback address.
    if not addresses:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect(("192.0.2.1", 9))
                address = IPv4Address(route.getsockname()[0])
                if not (address.is_loopback or address.is_unspecified):
                    addresses.add(str(address))
        except OSError:
            pass
    return tuple(sorted(addresses, key=lambda value: (IPv4Address(value).is_link_local, int(IPv4Address(value)))))


def access_hosts(host: str) -> tuple[str, ...]:
    host = normalize_bind_host(host)
    if host == DEFAULT_HOST:
        return *local_ipv4_addresses(), "127.0.0.1", "localhost"
    if host in {"127.0.0.1", "localhost"}:
        return "127.0.0.1", "localhost"
    return (host,)


def service_urls(host: str, port: int) -> tuple[str, ...]:
    hosts = access_hosts(host)
    return tuple(f"http://{value}:{port}" for value in hosts if value != "localhost")


def host_authorities(host: str, port: int) -> frozenset[str]:
    hosts = access_hosts(host)
    authorities = {f"{value}:{port}" for value in hosts}
    if port == 80:
        authorities.update(hosts)
    return frozenset(authorities)
