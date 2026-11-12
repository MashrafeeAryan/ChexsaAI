"""Read and submit a reviewed assignment using the Canvas API."""

import re
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
