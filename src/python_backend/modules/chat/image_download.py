"""受限图片下载：验证 DNS 并固定连接地址，禁止重定向到内网。"""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

from python_backend.modules.ai.errors import AIError


def download_image(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AIError("图片地址无效")
    if parsed.port not in (None, 80, 443):
        raise AIError("图片地址端口无效")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection = None
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise AIError("禁止下载内网图片")
        # socket 只连接已经验证的数值 IP；TLS 仍验证原始主机名。
        sock = socket.create_connection((addresses[0][4][0], port), timeout=30)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=30)
        connection.sock = sock
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("GET", path, headers={"Accept": "image/png,image/jpeg,image/webp"})
        response = connection.getresponse()
        mime = response.getheader("Content-Type", "").split(";", 1)[0].lower()
        if response.status != 200 or mime not in ("image/png", "image/jpeg", "image/webp"):
            raise AIError("图片下载失败或格式不支持", 502)
        data = response.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise AIError("图片超过 10 MB", 502)
        return data, mime
    except AIError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise AIError("图片下载失败", 502) from error
    finally:
        if connection:
            connection.close()
