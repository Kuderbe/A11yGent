"""Small shared helpers for command-line application setup."""

from urllib.parse import urlparse
from uuid import uuid4


def additional_headers_for(base_url: str) -> dict[str, str]:
    hostname = urlparse(base_url).hostname
    if hostname is None or not (hostname == "opencode.ai" or hostname.endswith(".opencode.ai")):
        return {}
    return {"x-opencode-session": str(uuid4())}