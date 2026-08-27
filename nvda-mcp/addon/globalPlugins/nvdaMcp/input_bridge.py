# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
Input injection for the NVDA MCP Bridge.

v1 ships one backend: :class:`KeyboardBackend`. It sends key gestures using
NVDA's own :class:`keyboardHandler.KeyboardInputGesture`, using a **two-tier
dispatch strategy**:

1. If the parsed gesture is bound to an NVDA script (e.g. ``NVDA+n``,
   ``NVDA+space``, or Browse-Mode quick-nav letters like ``h``/``d``/``k``),
   the gesture is dispatched directly through
   ``inputCore.manager.executeGesture()``. This is the only path that
   actually triggers NVDA scripts, because
   ``KeyboardInputGesture.send()`` wraps its OS-level ``keybd_event``
   calls in ``ignoreInjection()``, which makes NVDA's own low-level
   keyboard hook (``keyboardHandler.internal_keyDownEvent``) drop the
   injected keys before they can reach ``executeGesture``. Bypassing
   ``send()`` for NVDA-bound gestures avoids that filter.
2. If no NVDA script is bound (pure OS/app keystrokes such as ``tab``,
   ``control+l``, ``enter``, ``windows+d``, or literal characters typed
   via :meth:`KeyboardBackend.type_text`), the gesture falls back to
   ``KeyboardInputGesture.send()``, which uses
   ``winUser.keybd_event`` under ``ignoreInjection()`` so NVDA itself
   does not react to the synthetic keystrokes.

The :class:`InputBackend` protocol / :class:`BaseInputBackend` base class
is deliberately generic - future mouse or touch backends just implement
the same interface and register their own MCP tools.

All backend methods must be safe to call from **any** thread. Internally
they marshal to NVDA's wx main thread via
:func:`main_thread.run_on_main_thread` because ``keybd_event`` /
``SendInput`` and ``inputCore.manager.executeGesture`` must originate
from the process's UI thread.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Iterable, List

from . import config
from .main_thread import run_on_main_thread


class InputError(RuntimeError):
	"""Raised when an input operation fails (unknown key, cap exceeded, ...)."""


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseInputBackend(ABC):
	"""
	Abstract base for all input backends.

	Concrete subclasses expose one or more atomic actions (``send_key``,
	``click``, ``move``, …) that the MCP tool layer wraps.
	"""

	#: Human-readable name (used in logs and error messages).
	name: str = "input"

	@abstractmethod
	def is_available(self) -> bool:
		"""Return True if this backend can operate in the current environment."""


# ---------------------------------------------------------------------------
# Keyboard backend
# ---------------------------------------------------------------------------

class KeyboardBackend(BaseInputBackend):
	"""
	Simulate keyboard input via :class:`keyboardHandler.KeyboardInputGesture`.

	Accepted gesture strings are the same as NVDA's own gesture names, e.g.
	``"a"``, ``"control+shift+end"``, ``"downArrow"``, ``"pageDown"``,
	``"NVDA+f"``, ``"windows+d"``.
	"""

	name = "keyboard"

	def is_available(self) -> bool:
		try:
			import keyboardHandler  # noqa: F401  # type: ignore
			return True
		except Exception:  # noqa: BLE001
			return False

	# --- Primitive ----------------------------------------------------------

	def send_key(self, gesture: str) -> None:
		"""
		Send a single key or chord.

		:raises InputError: if the gesture name is not understood by NVDA.
		"""
		if not isinstance(gesture, str) or not gesture.strip():
			raise InputError("gesture must be a non-empty string")

		def _send() -> None:
			import keyboardHandler  # type: ignore
			import inputCore  # type: ignore

			try:
				kig = keyboardHandler.KeyboardInputGesture.fromName(gesture)
			except Exception as exc:  # noqa: BLE001
				raise InputError(f"Unknown key gesture {gesture!r}: {exc}") from exc

			# Two-tier dispatch (see module docstring for the full rationale):
			#
			# 1. If the gesture is bound to an NVDA script, dispatch it
			#    directly through ``inputCore.manager.executeGesture()``.
			#    This bypasses ``KeyboardInputGesture.send()``'s
			#    ``ignoreInjection()`` wrapper, which would otherwise cause
			#    NVDA's own low-level keyboard hook to drop the injected
			#    keys before they can reach ``executeGesture``. Without this
			#    bypass, gestures like ``NVDA+n``, ``NVDA+space``,
			#    ``NVDA+t``, ``NVDA+f7`` and every Browse-Mode quick-nav
			#    letter (``h``/``d``/``k``/``1..6``/...) would silently
			#    become no-ops.
			#
			# 2. If no NVDA script is bound (pure OS/app keystrokes such as
			#    ``tab``, ``control+l``, ``enter``, ``windows+d``, or
			#    literal characters from ``type_text``), fall back to
			#    ``kig.send()`` for OS-level keyboard injection.
			try:
				script = kig.script
			except Exception:  # noqa: BLE001
				# ``.script`` is a property; some gesture subclasses may
				# override it with a lookup that can raise. Treat any
				# failure as "no NVDA script bound" and fall through to
				# OS injection.
				script = None

			if script is not None:
				try:
					inputCore.manager.executeGesture(kig)
					return
				except inputCore.NoInputGestureAction:
					# Script disappeared between the lookup and the dispatch
					# (extremely unlikely, but defensive). Fall through to
					# OS injection so the caller still gets *some* effect.
					pass

			kig.send()

		run_on_main_thread(_send)

	# --- Convenience helpers -----------------------------------------------

	def send_keys(self, gestures: Iterable[str], delay_ms: int = 0) -> int:
		"""
		Send a sequence of key gestures. Returns the number sent.

		:param delay_ms: sleep this many milliseconds between keys. Sleep
			happens on the caller's (MCP server) thread, not the main
			thread, so it does not stall NVDA's UI.
		"""
		gestures = list(gestures)
		if len(gestures) > config.MAX_KEYS_PER_CALL:
			raise InputError(
				f"Refusing to send {len(gestures)} keys "
				f"(cap: {config.MAX_KEYS_PER_CALL})"
			)
		if delay_ms < 0:
			raise InputError("delay_ms must be >= 0")

		for i, g in enumerate(gestures):
			self.send_key(g)
			if delay_ms and i < len(gestures) - 1:
				time.sleep(delay_ms / 1000.0)
		return len(gestures)

	def type_text(self, text: str, delay_ms: int = 0) -> int:
		"""
		Type an arbitrary string by breaking it into per-character gestures.

		This uses ``KeyboardInputGesture.fromName(char)`` per character,
		which automatically figures out the required modifier keys via
		``VkKeyScanEx``. That means the current keyboard layout matters:
		typing ``"@"`` on a US layout works, but on some other layouts
		``VkKeyScanEx`` may fail. Characters that cannot be mapped are
		skipped and reported in the returned count.
		"""
		if len(text) > config.MAX_KEYS_PER_CALL:
			raise InputError(
				f"Refusing to type {len(text)} characters "
				f"(cap: {config.MAX_KEYS_PER_CALL})"
			)

		sent = 0
		for i, ch in enumerate(text):
			# Special-case newline: press Enter.
			gesture_name = _char_to_gesture_name(ch)
			try:
				self.send_key(gesture_name)
				sent += 1
			except InputError:
				# Skip characters we cannot map to a gesture rather than
				# aborting mid-string.
				continue
			if delay_ms and i < len(text) - 1:
				time.sleep(delay_ms / 1000.0)
		return sent


def _char_to_gesture_name(ch: str) -> str:
	"""Map a single character to a name understood by ``KeyboardInputGesture.fromName``."""
	if ch == "\n":
		return "enter"
	if ch == "\t":
		return "tab"
	if ch == " ":
		return "space"
	# NVDA's ``fromName`` special-cases '+' as the modifier separator, so a
	# literal plus must be spelled "plus".
	if ch == "+":
		return "plus"
	return ch


# ---------------------------------------------------------------------------
# Registry - future backends plug in here
# ---------------------------------------------------------------------------

class InputRegistry:
	"""
	Collects available input backends.

	The MCP server iterates this registry to decide which tools to expose.
	Adding mouse/touch support later means:

	1. Implement a new :class:`BaseInputBackend` subclass.
	2. ``registry.register(MyBackend())``.
	3. Add corresponding ``@mcp.tool`` wrappers in :mod:`mcp_server`.
	"""

	def __init__(self) -> None:
		self._backends: List[BaseInputBackend] = []

	def register(self, backend: BaseInputBackend) -> None:
		self._backends.append(backend)

	def get(self, name: str) -> BaseInputBackend | None:
		for b in self._backends:
			if b.name == name:
				return b
		return None

	def all(self) -> List[BaseInputBackend]:
		return list(self._backends)


def build_default_registry() -> InputRegistry:
	"""Registry containing all backends enabled in v1."""
	reg = InputRegistry()
	reg.register(KeyboardBackend())
	return reg