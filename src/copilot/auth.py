import asyncio
import re
import time
from typing import Any

import httpx
import jwt

from copilot.config import Settings

KEY_ID = re.compile(r"^[a-zA-Z0-9-]{1,80}$")
_key_cache: dict[tuple[str, str], str] = {}
_negative_key_cache: dict[tuple[str, str], float] = {}
_key_lock = asyncio.Lock()
NEGATIVE_KEY_CACHE_SECONDS = 30
NEGATIVE_KEY_CACHE_LIMIT = 128


class AuthenticationError(ValueError):
    pass


def _negative_key_is_cached(cache_key: tuple[str, str]) -> bool:
    expires_at = _negative_key_cache.get(cache_key, 0)
    if expires_at > time.monotonic():
        return True
    _negative_key_cache.pop(cache_key, None)
    return False


def _remember_negative_key(cache_key: tuple[str, str]) -> None:
    now = time.monotonic()
    for stored_key, expires_at in list(_negative_key_cache.items()):
        if expires_at <= now:
            _negative_key_cache.pop(stored_key, None)
    if len(_negative_key_cache) >= NEGATIVE_KEY_CACHE_LIMIT:
        oldest_key = min(_negative_key_cache, key=_negative_key_cache.__getitem__)
        _negative_key_cache.pop(oldest_key, None)
    _negative_key_cache[cache_key] = now + NEGATIVE_KEY_CACHE_SECONDS


async def verify_alb_claims(
    token: str,
    identity: str,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.aws_region or not settings.alb_arn or not settings.alb_client_id:
        raise AuthenticationError("ALB OIDC verification is not configured")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as error:
        raise AuthenticationError("ALB identity header is malformed") from error
    kid = str(header.get("kid", ""))
    if not KEY_ID.fullmatch(kid):
        raise AuthenticationError("ALB signing key identifier is invalid")
    if header.get("alg") != "ES256":
        raise AuthenticationError("ALB identity algorithm is not ES256")
    if header.get("signer") != settings.alb_arn:
        raise AuthenticationError("ALB signer does not match the configured load balancer")
    if header.get("client") != settings.alb_client_id:
        raise AuthenticationError("ALB client does not match the configured identity provider")
    try:
        expires_at = int(header["exp"])
    except (KeyError, TypeError, ValueError) as error:
        raise AuthenticationError("ALB identity expiration is missing") from error
    if expires_at <= int(time.time()):
        raise AuthenticationError("ALB identity has expired")

    public_key = await _public_key(settings.aws_region, kid)
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": False, "verify_exp": False},
        )
    except jwt.PyJWTError as error:
        raise AuthenticationError("ALB identity signature is invalid") from error
    if not identity or claims.get("sub") != identity:
        raise AuthenticationError("ALB identity subject does not match signed claims")
    return claims


async def _public_key(region: str, kid: str) -> str:
    cache_key = (region, kid)
    if cached := _key_cache.get(cache_key):
        return cached
    if _negative_key_is_cached(cache_key):
        raise AuthenticationError("ALB signing key is unavailable")
    async with _key_lock:
        if cached := _key_cache.get(cache_key):
            return cached
        if _negative_key_is_cached(cache_key):
            raise AuthenticationError("ALB signing key is unavailable")
        url = f"https://public-keys.auth.elb.{region}.amazonaws.com/{kid}"
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as error:
            _remember_negative_key(cache_key)
            raise AuthenticationError("ALB signing key could not be retrieved") from error
        key = response.text
        if "BEGIN PUBLIC KEY" not in key:
            _remember_negative_key(cache_key)
            raise AuthenticationError("ALB signing key response is invalid")
        _negative_key_cache.pop(cache_key, None)
        _key_cache[cache_key] = key
        return key
