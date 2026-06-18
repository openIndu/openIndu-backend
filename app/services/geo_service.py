"""Lightweight IP geo helpers for dashboard statistics."""
from __future__ import annotations

import ipaddress


GEO_POINTS: dict[str, dict[str, float | str]] = {
    "本地开发": {"country_code": "LOCAL", "lat": 31.2304, "lng": 121.4737},
    "中国": {"country_code": "CN", "lat": 35.8617, "lng": 104.1954},
    "美国": {"country_code": "US", "lat": 37.0902, "lng": -95.7129},
    "日本": {"country_code": "JP", "lat": 36.2048, "lng": 138.2529},
    "德国": {"country_code": "DE", "lat": 51.1657, "lng": 10.4515},
    "新加坡": {"country_code": "SG", "lat": 1.3521, "lng": 103.8198},
    "未知": {"country_code": "UNKNOWN", "lat": 20.0, "lng": 0.0},
}


def resolve_ip_geo(ip: str | None) -> dict[str, str | float]:
    """Resolve IP to a coarse dashboard geo point.

    The development environment does not ship a GeoIP database. For private/local
    addresses we return a deterministic local point; public addresses fall back to
    "未知" until a GeoIP database is configured in production.
    """
    if not ip:
        name = "未知"
    else:
        try:
            parsed = ipaddress.ip_address(ip)
            name = "本地开发" if parsed.is_private or parsed.is_loopback else "未知"
        except ValueError:
            name = "未知"
    point = GEO_POINTS[name]
    return {
        "name": name,
        "country_code": str(point["country_code"]),
        "lat": float(point["lat"]),
        "lng": float(point["lng"]),
    }
