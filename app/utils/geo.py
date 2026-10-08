"""
app/utils/geo.py — IP geo-location with a two-provider fallback chain.

Design principles
-----------------
* **Best-effort only**: A geo lookup failure must NEVER block or crash a
  submission.  Callers must wrap calls to this module in try/except and
  treat ``None`` as an acceptable result.
* **Short timeouts**: Each provider gets 2 seconds.  Total worst-case
  latency if both fail is ~4 s, which is acceptable for a background
  enrichment that the user never waits on directly.
* **Private-IP detection**: Local / loopback addresses (127.x, 10.x, etc.)
  are short-circuited immediately — geo APIs return errors for them and
  there is no useful data to collect.

Fallback chain
--------------
  1. ip-api.com  (free tier, no key required, 45 req/min)
  2. ipapi.co    (free tier, no key required, 30 req/min)
  3. None        (both failed → country_code saved as NULL)
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# Ordered list of (provider_name, url_template).
# The chain is tried top-to-bottom; the first successful response wins.
_GEO_PROVIDERS: list[tuple[str, str]] = [
    (
        "ip-api.com",
        "http://ip-api.com/json/{ip}?fields=status,countryCode,country,city,regionName",
    ),
    (
        "ipapi.co",
        "https://ipapi.co/{ip}/json/",
    ),
]

# IPs that are guaranteed to have no useful geo data.
_PRIVATE_PREFIXES = ("127.", "10.", "192.168.", "::1", "localhost")


def _is_private_ip(ip: str) -> bool:
    """Return True for loopback / RFC-1918 / link-local addresses."""
    return any(ip.startswith(prefix) for prefix in _PRIVATE_PREFIXES)


async def get_geo_data(ip: str) -> dict | None:
    """Query geo providers in order and return the first successful result.

    Parameters
    ----------
    ip:
        The raw client IP string (IPv4 or IPv6).

    Returns
    -------
    dict
        Raw JSON response from the first provider that succeeds.
        Keys differ by provider — use ``extract_country_code()`` to
        normalise them.
    None
        Returned when the IP is private, unknown, or all providers fail.
    """
    if not ip or _is_private_ip(ip):
        logger.debug("Skipping geo lookup for private/loopback IP: %s", ip)
        return None

    async with httpx.AsyncClient(timeout=2.0) as client:
        for provider_name, url_template in _GEO_PROVIDERS:
            url = url_template.format(ip=ip)
            try:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()

                # ip-api.com signals failure via {"status": "fail"} even on HTTP 200
                if payload.get("status") == "fail":
                    logger.debug(
                        "Geo provider %s returned status=fail for IP %s — skipping.",
                        provider_name, ip,
                    )
                    continue

                logger.debug(
                    "Geo data resolved via %s for IP %s: country=%s",
                    provider_name, ip,
                    payload.get("countryCode") or payload.get("country_code"),
                )
                return payload

            except httpx.TimeoutException:
                logger.warning(
                    "Geo provider %s timed out for IP %s — trying next provider.",
                    provider_name, ip,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Geo provider %s failed for IP %s: %s — trying next provider.",
                    provider_name, ip, exc,
                )

    logger.info(
        "All geo providers exhausted for IP %s — country_code will be NULL.", ip
    )
    return None


def extract_country_code(geo_data: dict | None) -> str | None:
    """Normalise the country code field across providers.

    Parameters
    ----------
    geo_data:
        Raw provider JSON, or None.

    Returns
    -------
    str or None
        Two-letter ISO 3166-1 alpha-2 country code, or None.

    Provider field mapping
    ----------------------
    * ip-api.com  → ``countryCode``  (e.g. ``"US"``)
    * ipapi.co    → ``country_code`` (e.g. ``"US"``)
    """
    if not geo_data:
        return None
    code = geo_data.get("countryCode") or geo_data.get("country_code")
    if isinstance(code, str) and len(code) == 2:
        return code.upper()
    return None
