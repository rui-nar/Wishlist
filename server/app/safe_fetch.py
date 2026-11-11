"""Fetching a URL a user typed, without letting it reach the server's network
(gift images plan D6).

Every URL, DNS answer, redirect and response is hostile. The fetcher connects
only to global unicast addresses on ports 80 and 443, to the very address it
vetted (a second DNS answer cannot move the connection), follows at most three
redirects, each vetted from scratch, and caps the time and the bytes.

The app holds one fetcher in `app.state.url_fetcher`; endpoint tests replace it
with a fake, and tests/test_safe_fetch.py runs this one against local servers
and a recording transport, so no test uses the network.
"""

import asyncio
import ipaddress
import logging
import socket
import zlib
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor

import httpx

_log = logging.getLogger(__name__)

MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
# The whole fetch, across hops and DNS lookups. The client's timeout for the
# from-url route is built on it (plan D6, review R1-5).
TOTAL_TIMEOUT = 20.0
ALLOWED_PORTS = (80, 443)

_REDIRECTS = {301, 302, 303, 307, 308}
_DEFAULT_PORTS = {"http": 80, "https": 443}
# NAT64 prefixes (RFC 6052, RFC 8215): the IPv4 address is the last 32 bits.
_NAT64 = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)
# getaddrinfo has no timeout. Lookups run here so the deadline can give up on
# one without waiting for it; a few threads are enough at a few hundred users.
_resolver_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="safe-fetch-dns")

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class FetchError(Exception):
    """A fetch that gave nothing. `code` is the API's error code, `reason` a
    fixed label for logs and tests; neither carries the URL."""

    code = ""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.host = "-"


class FetchRefused(FetchError):
    """The URL, or a redirect, points somewhere the server must not go."""

    code = "url_not_allowed"


class FetchFailed(FetchError):
    """The target was allowed but did not give an acceptable response."""

    code = "url_fetch_failed"


def address_allowed(ip: IPAddress) -> bool:
    """True for a global unicast address, and for an IPv6 address embedding an
    IPv4 one, only when that one is too."""
    if not _global_unicast(ip):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        return all(_global_unicast(embedded) for embedded in _embedded_ipv4(ip))
    return True


def _global_unicast(ip: IPAddress) -> bool:
    # is_global follows IANA's special-purpose registries (it already excludes
    # the shared 100.64/10 range and the limited broadcast); the other flags
    # are checked as well because is_global counts multicast as global.
    if (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # A global address never carries a zone.
        return not ip.is_site_local and ip.scope_id is None
    return True


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    embedded = []
    if ip.ipv4_mapped is not None:
        embedded.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        embedded.append(ip.sixtofour)
    if ip.teredo is not None:
        embedded.extend(ip.teredo)  # the relay and the client
    if any(ip in network for network in _NAT64):
        embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return embedded


def resolve_host(host: str) -> list[str]:
    """Every address the system resolver gives for `host`, in its order."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _default_transport() -> httpx.AsyncBaseTransport:
    # A transport per fetch, keeping no connection: a pooled connection to an
    # address, verified for one hostname, must never carry a request for
    # another. trust_env=False: no CA bundle or proxy from the environment.
    return httpx.AsyncHTTPTransport(
        trust_env=False,
        retries=0,
        limits=httpx.Limits(max_keepalive_connections=0),
    )


class SafeFetcher:
    """Constructed once. The defaults are production's; tests inject the
    resolver, the address predicate, the ports, the timeouts and the transport.
    """

    def __init__(
        self,
        *,
        resolve: Callable[[str], list[str]] = resolve_host,
        address_allowed: Callable[[IPAddress], bool] = address_allowed,
        ports: Collection[int] = ALLOWED_PORTS,
        connect_timeout: float = CONNECT_TIMEOUT,
        read_timeout: float = READ_TIMEOUT,
        total_timeout: float = TOTAL_TIMEOUT,
        transport: Callable[[], httpx.AsyncBaseTransport] = _default_transport,
        version: str = "dev",
    ) -> None:
        self._resolve = resolve
        self._address_allowed = address_allowed
        self._ports = frozenset(ports)
        self._timeouts = {
            "connect": connect_timeout,
            "read": read_timeout,
            "write": read_timeout,
            "pool": connect_timeout,
        }
        self._total_timeout = total_timeout
        self._transport = transport
        self._user_agent = f"ShushGift/{version}"

    def fetch(
        self, url: str, accept: Collection[str], max_bytes: int
    ) -> tuple[bytes, str]:
        """The body and its media type, or FetchRefused / FetchFailed.

        Blocking, for the app's sync handlers (run in a worker thread). It runs
        its own event loop: asyncio's cancellation is what holds the total
        deadline, which httpx's per-read timeouts alone cannot.
        """
        accepted = frozenset(media_type.lower() for media_type in accept)
        host = ["-"]  # the current hop's host, for the log line
        try:
            content, content_type = asyncio.run(
                self._fetch_within_deadline(url, accepted, max_bytes, host)
            )
        except FetchError as exc:
            exc.host = host[0]
            _log.warning(
                "url fetch: host=%s outcome=%s reason=%s",
                exc.host,
                exc.code,
                exc.reason,
            )
            raise
        _log.info(
            "url fetch: host=%s outcome=ok type=%s bytes=%d",
            host[0],
            content_type,
            len(content),
        )
        return content, content_type

    async def _fetch_within_deadline(
        self, url: str, accepted: frozenset[str], max_bytes: int, host: list[str]
    ) -> tuple[bytes, str]:
        try:
            async with asyncio.timeout(self._total_timeout):
                async with self._transport() as transport:
                    return await self._follow(transport, url, accepted, max_bytes, host)
        except TimeoutError:
            # from None, here and below: httpx's messages and the chained
            # traceback would carry the URL.
            raise FetchFailed("timeout") from None
        except httpx.HTTPError as exc:
            raise FetchFailed(f"transport:{type(exc).__name__}") from None

    async def _follow(
        self,
        transport: httpx.AsyncBaseTransport,
        url_text: str,
        accepted: frozenset[str],
        max_bytes: int,
        host: list[str],
    ) -> tuple[bytes, str]:
        url = self._parse(url_text)
        redirects = 0
        while True:
            host[0] = url.raw_host.decode("ascii")
            request = await self._pinned_request(url, accepted)
            response = await transport.handle_async_request(request)
            try:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchFailed("redirect_without_location")
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        raise FetchFailed("too_many_redirects")
                    try:
                        next_url = url.join(location)
                    except httpx.InvalidURL:
                        raise FetchRefused("invalid_url") from None
                    url = self._checked(next_url)
                    continue
                if response.status_code != 200:
                    raise FetchFailed(f"status:{response.status_code}")
                content_type = _media_type(response.headers.get("content-type", ""))
                if content_type not in accepted:
                    raise FetchFailed("content_type")
                return await _read_capped(response, max_bytes), content_type
            finally:
                await response.aclose()

    def _parse(self, url_text: str) -> httpx.URL:
        if len(url_text) > MAX_URL_LENGTH:
            raise FetchRefused("too_long")
        try:
            url = httpx.URL(url_text)
        except httpx.InvalidURL:
            raise FetchRefused("invalid_url") from None
        return self._checked(url)

    def _checked(self, url: httpx.URL) -> httpx.URL:
        """The URL rules, for the URL given and for every redirect."""
        if len(str(url)) > MAX_URL_LENGTH:
            raise FetchRefused("too_long")
        if url.scheme not in _DEFAULT_PORTS:
            raise FetchRefused("scheme")
        if url.userinfo:
            raise FetchRefused("userinfo")
        if not url.raw_host:
            raise FetchRefused("no_host")
        port = url.port if url.port is not None else _DEFAULT_PORTS[url.scheme]
        if port not in self._ports:
            raise FetchRefused("port")
        return url

    async def _pinned_request(
        self, url: httpx.URL, accepted: frozenset[str]
    ) -> httpx.Request:
        """A request to the vetted address itself, named for the host."""
        name = url.raw_host.decode("ascii")
        address = await self._vetted_address(name)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        extensions: dict[str, object] = {"timeout": dict(self._timeouts)}
        if url.scheme == "https":
            # httpcore sends this name as SNI and verifies the certificate
            # against it, while the socket goes to the address.
            extensions["sni_hostname"] = name
        return httpx.Request(
            "GET",
            url.copy_with(host=str(address)),
            headers={
                "Host": url.netloc.decode("ascii"),
                "Accept": ", ".join(sorted(accepted)),
                # Bodies come uncompressed when the server listens; one that
                # compresses anyway is decoded under the cap (_read_capped).
                "Accept-Encoding": "identity",
                "User-Agent": self._user_agent,
            },
            extensions=extensions,
        )

    async def _vetted_address(self, name: str) -> IPAddress:
        """The first address `name` resolves to, once every one is allowed."""
        literal = _ip_literal(name)
        addresses = [literal] if literal is not None else await self._resolved(name)
        if not all(self._address_allowed(address) for address in addresses):
            raise FetchRefused("address")
        return addresses[0]

    async def _resolved(self, name: str) -> list[IPAddress]:
        loop = asyncio.get_running_loop()
        try:
            answers = await loop.run_in_executor(_resolver_pool, self._resolve, name)
        except OSError:
            raise FetchFailed("dns") from None
        if not answers:
            raise FetchFailed("dns")
        addresses = []
        for answer in answers:
            address = _ip_literal(answer)
            if address is None:
                raise FetchRefused("address")
            addresses.append(address)
        return addresses


def _ip_literal(text: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    """The body, refused as soon as it exceeds `max_bytes`, decoded or not."""
    declared = response.headers.get("content-length")
    if (
        declared is not None
        and declared.strip().isdigit()
        and int(declared) > max_bytes
    ):
        raise FetchFailed("too_large")
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding in ("gzip", "x-gzip", "deflate"):
        # 32 + MAX_WBITS: a gzip or zlib header, detected.
        decoder = zlib.decompressobj(32 + zlib.MAX_WBITS)
    elif encoding == "identity":
        decoder = None
    else:
        raise FetchFailed("content_encoding")

    body = bytearray()
    received = 0
    async for chunk in response.aiter_raw():
        received += len(chunk)
        if received > max_bytes:
            raise FetchFailed("too_large")
        if decoder is None:
            body += chunk
            continue
        try:
            # Bounded output per call: a small compressed chunk can expand a
            # thousandfold, and must not reach memory before it is counted.
            data = chunk
            while data:
                body += decoder.decompress(data, max_bytes - len(body) + 1)
                if len(body) > max_bytes:
                    raise FetchFailed("too_large")
                data = decoder.unconsumed_tail
        except zlib.error:
            raise FetchFailed("content_encoding") from None
    if decoder is not None and not decoder.eof:
        raise FetchFailed("content_encoding")
    return bytes(body)
