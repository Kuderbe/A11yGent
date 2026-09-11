# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
Static configuration constants for the NVDA MCP Bridge.

For v1 these are simple module-level constants so we do not depend on the
NVDA settings framework yet. When we later add a Settings panel, the panel
will just write to a config dict and these constants will become the
defaults.
"""

from __future__ import annotations

import socket


# --- Network binding ---------------------------------------------------------


def _detect_primary_ipv4() -> str:
	"""
	Return the primary non-loopback IPv4 address of this host.

	This mirrors what ``ipconfig`` on Windows (or ``ifconfig`` on POSIX)
	shows as the active IPv4 on the primary network adapter.

	Strategy (both steps skip ``127.0.0.0/8`` and ``169.254.0.0/16``):

	1. Ask the resolver for all IPv4s bound to the current hostname
	   (``socket.gethostbyname_ex(gethostname())``). Fast, no network
	   traffic. Works on Windows because Windows registers each NIC's
	   IPv4 with the local resolver.

	2. Fallback: open a UDP socket and ``connect`` it to a public
	   sentinel address. This does NOT send any packet — ``connect``
	   on a UDP socket just picks the local endpoint that the kernel
	   would use for that destination. ``getsockname()`` then reveals
	   the local IPv4 of the outbound interface. This is the
	   idiomatic cross-platform "which IP am I?" trick, and it works
	   even when the hostname resolves only to ``127.0.0.1`` (which
	   is common on macOS defaults).

	Both steps fall through to ``127.0.0.1`` on total failure (host
	offline, no interfaces up).
	"""
	# Step 1: hostname lookup
	try:
		hostname = socket.gethostname()
		_hostname, _aliases, addresses = socket.gethostbyname_ex(hostname)
	except OSError:
		addresses = []
	for ip in addresses:
		if not ip:
			continue
		if ip.startswith("127.") or ip.startswith("169.254."):
			continue
		return ip

	# Step 2: outbound-route probe
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	try:
		s.settimeout(0.5)
		# Any public IP works; nothing is actually sent.
		s.connect(("8.8.8.8", 53))
		ip = s.getsockname()[0]
	except OSError:
		ip = "127.0.0.1"
	finally:
		s.close()
	if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
		return ip
	return "127.0.0.1"


#: Interface the MCP HTTP server binds to.
#:
#: We resolve this to whatever the OS reports as the primary IPv4 on
#: the current host (i.e. the address that ``ipconfig`` / ``ifconfig``
#: would show), so the server is reachable from other machines on the
#: same LAN without any manual configuration. To restrict to localhost
#: only, override to ``"127.0.0.1"``.
#:
#: NOTE: no authentication is enabled by default. Binding to a
#: non-loopback address means every host on the LAN can drive NVDA
#: through this server. Only do this in a trusted network (dev VM
#: on a private subnet).
MCP_HOST: str = _detect_primary_ipv4()

#: TCP port the MCP HTTP server listens on.
MCP_PORT: int = 8765

#: URL path prefix for the Streamable HTTP MCP endpoint.
#: Full URL will be:  http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}
MCP_PATH: str = "/mcp"


# --- Server behaviour --------------------------------------------------------

#: Human-readable server name advertised to MCP clients.
MCP_SERVER_NAME: str = "nvda-mcp"

#: Server version reported to MCP clients.
MCP_SERVER_VERSION: str = "0.2.0"

#: Whether to auto-start the MCP server when the plugin loads.
AUTO_START: bool = True


# --- Speech log --------------------------------------------------------------

#: Maximum number of spoken utterances retained in memory.
SPEECH_LOG_MAX_ENTRIES: int = 1000


# --- Input --------------------------------------------------------------

#: Default delay (milliseconds) between successive keys in ``send_keys`` /
#: ``type_text``. 0 means "as fast as possible".
DEFAULT_KEY_DELAY_MS: int = 0

#: Hard safety cap on how many keys a single ``send_keys`` / ``type_text``
#: call is allowed to inject, to protect against runaway agents.
MAX_KEYS_PER_CALL: int = 4096


# --- Auth --------------------------------------------------------------

#: Enable authentication. In v1 we ship ``AllowAllAuth`` so this flag has
#: no visible effect, but the plumbing is in place for a future token /
#: bearer auth backend.
ENABLE_AUTH: bool = False

#: Optional pre-shared token. Ignored while ENABLE_AUTH is False.
AUTH_TOKEN: str | None = None


# --- Main-thread marshalling --------------------------------------------------------------

#: Timeout in seconds for a synchronous call from the MCP server thread
#: back onto NVDA's wx main thread. Should stay short: real NVDA API calls
#: are effectively instant. If we hit this, the main loop is stuck.
MAIN_THREAD_CALL_TIMEOUT: float = 5.0