"""Read and submit a reviewed assignment using the Canvas API."""

from html import unescape
import re

import httpx
from urllib.parse import urlsplit


def canvas_origin(url):
    """Return a clean HTTPS address for one Canvas school."""
    address = urlsplit(url)
    if (
        address.scheme != "https"
        or not address.hostname
        or address.username is not None
        or address.password is not None
        or any(char.isspace() or char == chr(92) for char in url)
    ):
        raise ValueError("Use a Canvas HTTPS link without a login in it.")
    host = address.hostname
    if ":" in host:
        host = "[" + host + "]"
    port = address.port
    return f"https://{host}:{port}" if port not in (None, 443) else f"https://{host}"


def assignment_path(url, school):
    """Check the school before turning a link into an API path."""
    if canvas_origin(url) != canvas_origin(school):
        raise ValueError("The assignment link must belong to your configured Canvas school.")
    path = urlsplit(url).path.rstrip("/")
    if not re.fullmatch(r"/courses/[1-9][0-9]*/assignments/[1-9][0-9]*", path):
        raise ValueError("Paste the link to one Canvas assignment.")
    return path


def canvas_request(client, school, token, method, path, **kwargs):
    """Send the Canvas token only to the configured school."""
    try:
        response = client.request(
            method, school + "/api/v1" + path,
            headers={"Authorization": "Bearer " + token},
            follow_redirects=False, **kwargs,
        )
    except httpx.HTTPError:
        raise RuntimeError("Could not reach Canvas. Check your connection and Canvas settings.") from None
    return canvas_json(response)


def canvas_json(response):
    """Read an API result without printing secret headers or server errors."""
    if not response.is_success:
        raise RuntimeError(f"Canvas returned HTTP {response.status_code}. Check your access and assignment.")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("Canvas did not return assignment data.") from None
    if not isinstance(result, dict):
        raise RuntimeError("Canvas returned an unexpected response.")
    return result


def assignment_details(client, school, token, path):
    """Get the assignment and check that it is the one we asked for."""
    details = canvas_request(client, school, token, "GET", path)
    if str(details.get("id")) != path.rsplit("/", 1)[-1]:
        raise RuntimeError("Canvas returned a different assignment.")
    return details


def assignment_text(html):
    """Keep the written instructions and paragraph breaks."""
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", html or "", flags=re.I | re.S)
    html = re.sub(r"<(?:br\b[^>]*|/(?:p|div|li|h[1-6]))\s*/?>", "\n", html, flags=re.I)
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()
