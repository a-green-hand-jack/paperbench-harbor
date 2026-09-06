"""Direct HTTPS retrieval: validate the connected peer before TLS or HTTP data."""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection((self.host, self.port), self.timeout)
        try:
            if not ipaddress.ip_address(raw.getpeername()[0]).is_global:
                raise ValueError("source connection reached a non-public address")
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def retrieve(url):
    for _ in range(10):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("sources require credential-free public HTTPS URLs")
        connection = PublicHTTPS(
            parsed.hostname, parsed.port or 443, timeout=60, context=ssl.create_default_context()
        )
        try:
            connection.request(
                "GET",
                (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
                headers={"User-Agent": "PaperSmith/0.2", "Accept-Encoding": "identity"},
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("source redirect has no destination")
                url = urljoin(url, location)
                continue
            if response.status in {429, 500, 502, 503, 504}:
                raise RuntimeError("source server temporarily unavailable; resume")
            if response.status != 200:
                raise ValueError(
                    f"source HTTP status {response.status}; select accessible evidence"
                )
            data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError("source exceeds 64 MiB; supply a scoped source")
            return (
                data,
                response.headers.get_content_type(),
                url,
                {
                    key: response.getheader(key)
                    for key in ("ETag", "Last-Modified", "Link", "Content-Location")
                    if response.getheader(key)
                },
            )
        finally:
            connection.close()
    raise ValueError("source redirect limit exceeded")
