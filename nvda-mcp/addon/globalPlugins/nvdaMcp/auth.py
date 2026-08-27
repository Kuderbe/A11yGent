# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
Authentication abstraction for the NVDA MCP Bridge.

v1 always uses :class:`AllowAllAuth`. The abstraction exists so that a
future token- or bearer-based auth provider can be dropped in without
touching the tool implementations.

Design intent
-------------
The MCP SDK's Streamable HTTP transport gives us access to the incoming
HTTP request headers via the FastMCP ``Context`` object. An auth provider
receives whatever request metadata is available (headers dict) and returns
either ``True`` (allow) or raises :class:`AuthError` (deny).

We deliberately keep the interface tiny and synchronous - most auth checks
are either a constant-time token comparison or a stub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Optional


class AuthError(Exception):
	"""Raised by an :class:`AuthProvider` to signal a rejected request."""


class AuthProvider(ABC):
	"""
	Abstract base class for authentication providers.

	Implementations must be thread-safe: ``authenticate`` can be called from
	any thread that services an MCP tool invocation.
	"""

	@abstractmethod
	def authenticate(self, headers: Optional[Mapping[str, str]] = None) -> None:
		"""
		Validate an incoming request.

		:param headers: HTTP request headers (lower-cased keys) if available,
			or ``None`` when the transport does not expose them (in-process
			test calls, for example).
		:raises AuthError: if the request must be rejected.
		"""


class AllowAllAuth(AuthProvider):
	"""No-op auth provider. Accepts every request. Default in v1."""

	def authenticate(self, headers: Optional[Mapping[str, str]] = None) -> None:  # noqa: D401
		return None


class BearerTokenAuth(AuthProvider):
	"""
	Simple ``Authorization: Bearer <token>`` provider.

	Not wired up in v1 - kept here as a reference implementation showing
	how a future auth mode plugs in without changing the tool layer.
	"""

	def __init__(self, expected_token: str) -> None:
		if not expected_token:
			raise ValueError("expected_token must be a non-empty string")
		self._expected = expected_token

	def authenticate(self, headers: Optional[Mapping[str, str]] = None) -> None:
		if headers is None:
			raise AuthError("Missing request headers; cannot authenticate")
		# Header names in Starlette are lower-cased.
		value = headers.get("authorization") or headers.get("Authorization")
		if not value:
			raise AuthError("Missing Authorization header")
		parts = value.split(None, 1)
		if len(parts) != 2 or parts[0].lower() != "bearer":
			raise AuthError("Malformed Authorization header")
		# NB: constant-time comparison would be preferable in production.
		if parts[1] != self._expected:
			raise AuthError("Invalid bearer token")


def build_default_auth() -> AuthProvider:
	"""
	Build the auth provider selected by :mod:`config`.

	Called once at plugin start-up.
	"""
	# Local import to avoid a circular dependency at module load time.
	from . import config

	if config.ENABLE_AUTH and config.AUTH_TOKEN:
		return BearerTokenAuth(config.AUTH_TOKEN)
	return AllowAllAuth()