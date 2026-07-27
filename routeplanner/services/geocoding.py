import hashlib

import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import GeocodingError


def _cache_key(query: str) -> str:
    normalized = query.strip().lower()
    digest = hashlib.sha1(normalized.encode()).hexdigest()
    return f"geocode:{digest}"


def geocode_location(query: str):
    """Resolve a free-text location (e.g. "Chicago, IL") to (lat, lon) via
    Nominatim. Raises GeocodingError if nothing matches within the US.

    Cached (Redis in production, in-process locmem otherwise): place
    coordinates don't change, so repeat lookups of the same city/address
    across requests skip Nominatim entirely -- this is the caching that
    matters most here, since it directly cuts down calls to the free,
    rate-limited geocoding service the same way skipping it via explicit
    lat/lon does.
    """
    cache_key = _cache_key(query)
    cached = cache.get(cache_key)
    if cached is not None:
        return tuple(cached)

    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": settings.NOMINATIM_USER_AGENT}

    try:
        resp = requests.get(
            f"{settings.NOMINATIM_BASE_URL}/search", params=params, headers=headers, timeout=10
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding service unavailable: {exc}") from exc

    if not results:
        raise GeocodingError(f"Could not find a US location matching '{query}'")

    coords = (float(results[0]["lat"]), float(results[0]["lon"]))
    cache.set(cache_key, coords, timeout=settings.GEOCODE_CACHE_TTL_SECONDS)
    return coords
