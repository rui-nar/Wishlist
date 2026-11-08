"""The safe URL fetcher (gift images plan D6), without the network: local HTTP
servers on 127.0.0.1 and 127.0.0.2 with an injected resolver and address
predicate, and a recording transport for what is sent over https."""

import gzip
import http.server
import ipaddress
import logging
import socketserver
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest

from app.safe_fetch import (
    FetchFailed,
    FetchRefused,
    SafeFetcher,
    address_allowed,
)

PNG = ("image/png",)
CAP = 1000
ALLOWED = "127.0.0.1"
REFUSED = "127.0.0.2"


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "fe80::1",
        "fc00::1",
        "fec0::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "2002:7f00:1::1",
        "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo of 127.0.0.1
        "64:ff9b::7f00:1",
        "64:ff9b:1::7f00:1",
    ],
)
def test_a_non_global_address_is_refused(address):
    assert not address_allowed(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700::1111", "::ffff:8.8.8.8"])
def test_a_global_address_is_allowed(address):
    assert address_allowed(ipaddress.ip_address(address))


# Local servers.


class _HTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks up the address's name, which can take
        # seconds for 127.0.0.2 (Windows); no handler here needs it.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Server:
    """An HTTP server on one loopback address, answering by path and
    recording every request it receives."""

    def __init__(self, host: str) -> None:
        self.routes: dict[
            str, Callable[[http.server.BaseHTTPRequestHandler], None]
        ] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.stop = threading.Event()
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.requests.append((self.path, dict(self.headers)))
                route = server.routes.get(self.path.split("?")[0])
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                route(self)

            def log_message(self, *args) -> None:
                pass

        self.httpd = _HTTPServer((host, 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, args=(0.05,), daemon=True
        )
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def png(body: bytes = b"\x89PNG-bytes", **headers: str):
    def answer(handler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        for name, value in headers.items():
            handler.send_header(name.replace("_", "-"), value)
        handler.end_headers()
        handler.wfile.write(body)

    return answer


def redirect(location: str, status: int = 302):
    def answer(handler) -> None:
        handler.send_response(status)
        handler.send_header("Location", location)
        handler.send_header("Set-Cookie", "session=secret")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    return answer


@pytest.fixture
def servers() -> Iterator[tuple[Server, Server]]:
    allowed, refused = Server(ALLOWED), Server(REFUSED)
    yield allowed, refused
    allowed.close()
    refused.close()


def local_fetcher(
    servers: tuple[Server, Server],
    resolve: Callable[[str], list[str]] | None = None,
    **options,
) -> SafeFetcher:
    """A fetcher whose only allowed address is 127.0.0.1, with the servers'
    ports allowed and names resolved to the servers."""
    names = {"allowed.test": [ALLOWED], "refused.test": [REFUSED]}
    return SafeFetcher(
        resolve=resolve or (lambda host: names[host]),
        address_allowed=lambda ip: ip == ipaddress.ip_address(ALLOWED),
        ports=(servers[0].port, servers[1].port),
        **options,
    )


def test_an_allowed_url_gives_the_body_and_its_media_type(servers):
    allowed, _ = servers
    allowed.routes["/a.png"] = png()

    content, content_type = local_fetcher(servers).fetch(
        f"http://allowed.test:{allowed.port}/a.png", PNG, CAP
    )

    assert (content, content_type) == (b"\x89PNG-bytes", "image/png")
    path, headers = allowed.requests[0]
    assert headers["Host"] == f"allowed.test:{allowed.port}"
    assert headers["Accept"] == "image/png"
    assert headers["User-Agent"] == "Wishlist/dev"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/a.png",
        "file:///etc/passwd",
        "http://user:pass@example.com/a.png",
        "http://user@example.com/a.png",
        "http://example.com:8080/a.png",
        "http://example.com/" + "a" * (2049 - len("http://example.com/")),
        "http:///a.png",
        "not a url",
    ],
)
def test_a_url_outside_the_rules_is_refused_before_any_lookup(url):
    looked_up: list[str] = []
    fetcher = SafeFetcher(resolve=lambda host: looked_up.append(host) or ["8.8.8.8"])

    with pytest.raises(FetchRefused) as refused:
        fetcher.fetch(url, PNG, CAP)

    assert refused.value.code == "url_not_allowed"
    assert looked_up == []


def test_a_2048_character_url_is_not_refused_for_its_length():
    url = "http://example.com/" + "a" * (2048 - len("http://example.com/"))
    assert len(url) == 2048

    with pytest.raises(FetchRefused) as refused:
        SafeFetcher(resolve=lambda host: ["10.0.0.1"]).fetch(url, PNG, CAP)

    assert refused.value.reason == "address"


@pytest.mark.parametrize("host", ["refused.test", REFUSED])
def test_a_redirect_to_a_refused_address_is_refused_and_never_reached(servers, host):
    allowed, refused = servers
    allowed.routes["/go"] = redirect(f"http://{host}:{refused.port}/a.png")
    refused.routes["/a.png"] = png()

    with pytest.raises(FetchRefused) as error:
        local_fetcher(servers).fetch(f"http://allowed.test:{allowed.port}/go", PNG, CAP)

    assert error.value.reason == "address"
    assert refused.requests == []


def test_a_second_dns_answer_cannot_move_the_connection(servers):
    allowed, refused = servers
    allowed.routes["/a.png"] = png()
    refused.routes["/a.png"] = png(b"rebound")
    answers = iter([[ALLOWED], [REFUSED], [REFUSED]])

    content, _ = local_fetcher(servers, resolve=lambda host: next(answers)).fetch(
        f"http://rebind.test:{allowed.port}/a.png", PNG, CAP
    )

    assert content == b"\x89PNG-bytes"
    assert len(allowed.requests) == 1
    assert refused.requests == []


def test_a_host_with_one_refused_address_among_its_answers_is_refused(servers):
    allowed, refused = servers
    allowed.routes["/a.png"] = png()

    with pytest.raises(FetchRefused):
        local_fetcher(servers, resolve=lambda host: [ALLOWED, REFUSED]).fetch(
            f"http://mixed.test:{allowed.port}/a.png", PNG, CAP
        )

    assert allowed.requests == []
    assert refused.requests == []


def test_three_redirects_are_followed_and_a_fourth_fails(servers):
    allowed, _ = servers
    for hop in range(4):
        allowed.routes[f"/r{hop}"] = redirect(f"/r{hop + 1}")
    allowed.routes["/r4"] = png()
    url = f"http://allowed.test:{allowed.port}"
    fetcher = local_fetcher(servers)

    assert fetcher.fetch(f"{url}/r1", PNG, CAP)[0] == b"\x89PNG-bytes"
    with pytest.raises(FetchFailed) as failed:
        fetcher.fetch(f"{url}/r0", PNG, CAP)

    assert failed.value.reason == "too_many_redirects"
    assert "/r4" not in [path for path, _ in allowed.requests[4:]]


def test_a_redirect_to_another_port_is_refused(servers):
    allowed, _ = servers
    allowed.routes["/go"] = redirect("http://allowed.test:8080/a.png")

    with pytest.raises(FetchRefused) as refused:
        local_fetcher(servers).fetch(f"http://allowed.test:{allowed.port}/go", PNG, CAP)

    assert refused.value.reason == "port"


def stalled_body(stop: threading.Event):
    def answer(handler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.end_headers()
        # A byte at a time, well within the read timeout, forever.
        while not stop.wait(0.1):
            handler.wfile.write(b"x")
            handler.wfile.flush()

    return answer


def answer_with(status: int = 200, content_type: str = "image/png", **headers: str):
    def answer(handler) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        for name, value in headers.items():
            handler.send_header(name.replace("_", "-"), value)
        handler.end_headers()
        handler.wfile.write(b"x" * 10)

    return answer


@pytest.mark.parametrize(
    ("route", "reason"),
    [
        (answer_with(status=404), "status:404"),
        (answer_with(status=204), "status:204"),
        (answer_with(content_type="text/html"), "content_type"),
        (answer_with(content_length=str(CAP + 1)), "too_large"),
        (png(b"x" * (CAP + 1)), "too_large"),
        (png(gzip.compress(b"\0" * 1_000_000), content_encoding="gzip"), "too_large"),
        (png(b"x", content_encoding="br"), "content_encoding"),
        (redirect(""), "redirect_without_location"),
    ],
)
def test_an_unacceptable_response_fails(servers, route, reason):
    allowed, _ = servers
    allowed.routes["/a"] = route

    with pytest.raises(FetchFailed) as failed:
        local_fetcher(servers).fetch(f"http://allowed.test:{allowed.port}/a", PNG, CAP)

    assert failed.value.code == "url_fetch_failed"
    assert failed.value.reason == reason


def test_a_body_at_the_cap_and_a_compressed_body_under_it_are_accepted(servers):
    allowed, _ = servers
    allowed.routes["/full"] = png(b"x" * CAP)
    allowed.routes["/gzip"] = png(gzip.compress(b"y" * CAP), content_encoding="gzip")
    allowed.routes["/type"] = answer_with(content_type="Image/PNG; charset=binary")
    url = f"http://allowed.test:{allowed.port}"
    fetcher = local_fetcher(servers)

    assert fetcher.fetch(f"{url}/full", PNG, CAP)[0] == b"x" * CAP
    assert fetcher.fetch(f"{url}/gzip", PNG, CAP)[0] == b"y" * CAP
    assert fetcher.fetch(f"{url}/type", PNG, CAP)[1] == "image/png"


def test_a_content_length_below_the_body_never_reads_past_it(servers):
    allowed, _ = servers
    allowed.routes["/a"] = png(b"x" * (CAP * 10), content_length="5")

    content, _ = local_fetcher(servers).fetch(
        f"http://allowed.test:{allowed.port}/a", PNG, CAP
    )

    assert content == b"xxxxx"


def test_a_server_dribbling_past_the_deadline_fails_within_it(servers):
    allowed, _ = servers
    allowed.routes["/slow"] = stalled_body(allowed.stop)
    fetcher = local_fetcher(servers, total_timeout=1.0)

    started = time.monotonic()
    with pytest.raises(FetchFailed) as failed:
        fetcher.fetch(f"http://allowed.test:{allowed.port}/slow", PNG, 10**9)

    assert failed.value.reason == "timeout"
    assert time.monotonic() - started < 2.0


def test_a_lookup_past_the_deadline_fails_within_it():
    release = threading.Event()

    def hanging(host: str) -> list[str]:
        release.wait(5)
        return ["8.8.8.8"]

    started = time.monotonic()
    try:
        with pytest.raises(FetchFailed) as failed:
            SafeFetcher(resolve=hanging, total_timeout=0.5).fetch(
                "http://slow-dns.test/a.png", PNG, CAP
            )
    finally:
        release.set()

    assert failed.value.reason == "timeout"
    assert time.monotonic() - started < 1.5


def test_proxies_in_the_environment_are_ignored(servers, monkeypatch):
    allowed, refused = servers
    allowed.routes["/a.png"] = png()
    proxy = f"http://{REFUSED}:{refused.port}"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(name, proxy)

    local_fetcher(servers).fetch(f"http://allowed.test:{allowed.port}/a.png", PNG, CAP)

    assert len(allowed.requests) == 1
    assert refused.requests == []


def test_the_log_names_the_host_and_outcome_but_never_the_url(servers, caplog):
    allowed, _ = servers
    allowed.routes["/a.png"] = png()
    secret = "token=s3cret"
    fetcher = local_fetcher(servers)

    with caplog.at_level(logging.INFO, logger="app.safe_fetch"):
        fetcher.fetch(f"http://allowed.test:{allowed.port}/a.png?{secret}", PNG, CAP)
        with pytest.raises(FetchFailed):
            fetcher.fetch(
                f"http://allowed.test:{allowed.port}/missing?{secret}", PNG, CAP
            )

    assert "host=allowed.test outcome=ok" in caplog.text
    assert "host=allowed.test outcome=url_fetch_failed reason=status:404" in caplog.text
    assert secret not in caplog.text


# What is sent, recorded.


class Recorder:
    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self.responses = responses

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses[request.url.path]


def test_https_goes_to_the_vetted_address_named_for_the_host():
    recorder = Recorder(
        {
            "/go": httpx.Response(
                302,
                headers={"Location": "https://cdn.example/a.png", "Set-Cookie": "s=1"},
            ),
            "/a.png": httpx.Response(
                200,
                headers={"Content-Type": "image/png"},
                stream=httpx.ByteStream(b"img"),
            ),
        }
    )
    names = {"shop.example": ["93.184.215.14"], "cdn.example": ["2606:4700::1111"]}
    fetcher = SafeFetcher(resolve=names.__getitem__, transport=recorder.transport)

    assert fetcher.fetch("https://shop.example/go", PNG, CAP) == (b"img", "image/png")

    first, second = recorder.requests
    assert str(first.url) == "https://93.184.215.14/go"
    assert first.headers["Host"] == "shop.example"
    assert first.extensions["sni_hostname"] == "shop.example"
    assert str(second.url) == "https://[2606:4700::1111]/a.png"
    assert second.headers["Host"] == "cdn.example"
    assert second.extensions["sni_hostname"] == "cdn.example"
    for request in recorder.requests:
        assert "Cookie" not in request.headers
        assert "Authorization" not in request.headers


def test_an_international_host_is_resolved_and_named_in_its_ascii_form():
    recorder = Recorder(
        {
            "/a.png": httpx.Response(
                200,
                headers={"Content-Type": "image/png"},
                stream=httpx.ByteStream(b"img"),
            )
        }
    )
    looked_up: list[str] = []

    def resolve(host: str) -> list[str]:
        looked_up.append(host)
        return ["93.184.215.14"]

    SafeFetcher(resolve=resolve, transport=recorder.transport).fetch(
        "https://bücher.example/a.png", PNG, CAP
    )

    assert looked_up == ["xn--bcher-kva.example"]
    assert recorder.requests[0].headers["Host"] == "xn--bcher-kva.example"
    assert recorder.requests[0].extensions["sni_hostname"] == "xn--bcher-kva.example"


def test_a_name_resolving_to_the_metadata_address_is_refused_by_default():
    recorder = Recorder({})

    with pytest.raises(FetchRefused):
        SafeFetcher(
            resolve=lambda host: ["169.254.169.254"], transport=recorder.transport
        ).fetch("http://metadata.example/latest", PNG, CAP)

    assert recorder.requests == []


def test_an_unresolvable_host_fails():
    def nxdomain(host: str) -> list[str]:
        raise OSError("no such host")

    with pytest.raises(FetchFailed) as failed:
        SafeFetcher(resolve=nxdomain).fetch("http://nowhere.example/a.png", PNG, CAP)

    assert failed.value.reason == "dns"
