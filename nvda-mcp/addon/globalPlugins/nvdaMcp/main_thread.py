# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
Helper for marshalling calls onto NVDA's main thread.

Almost every NVDA API (``api.getFocusObject``,
``keyboardHandler.KeyboardInputGesture.send``, ``ui.message``, …) must be
called on the wx main thread. The MCP server, however, runs its request
handlers on a background asyncio thread. This module offers a small,
synchronous ``run_on_main_thread`` helper that:

1. Schedules a callable on the wx main loop via ``wx.CallAfter``.
2. Blocks the caller until the callable finishes (or raises).
3. Re-raises the exception on the caller's thread.

It also gracefully degrades when wx is not available (e.g. during unit
tests or when the module is imported outside of NVDA): the callable is
simply executed inline on the current thread.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar

from . import config

try:  # pragma: no cover - wx only exists inside NVDA.
	import wx  # type: ignore
	_HAS_WX = True
except Exception:  # noqa: BLE001
	wx = None  # type: ignore
	_HAS_WX = False


T = TypeVar("T")


class MainThreadCallTimeout(RuntimeError):
	"""Raised when a main-thread call does not complete within the timeout."""


def run_on_main_thread(
	fn: Callable[..., T],
	*args: Any,
	timeout: float | None = None,
	**kwargs: Any,
) -> T:
	"""
	Run ``fn(*args, **kwargs)`` on NVDA's wx main thread and return its result.

	If the current thread *is* the wx main thread, the call happens inline to
	avoid deadlock. If wx is not available at all, the call is also inline.

	:param timeout: seconds to wait before raising :class:`MainThreadCallTimeout`.
		Defaults to :data:`config.MAIN_THREAD_CALL_TIMEOUT`.
	:raises MainThreadCallTimeout: if the main thread does not process the
		call within ``timeout`` seconds.
	:raises BaseException: any exception raised by ``fn`` is re-raised here.
	"""
	if timeout is None:
		timeout = config.MAIN_THREAD_CALL_TIMEOUT

	if not _HAS_WX or wx is None:
		return fn(*args, **kwargs)

	# If we are already on the main thread, calling wx.CallAfter and then
	# blocking on an Event would deadlock (the event loop can only dispatch
	# the queued call once we return control). Detect and short-circuit.
	if wx.IsMainThread():
		return fn(*args, **kwargs)

	done = threading.Event()
	box: dict[str, Any] = {}

	def _runner() -> None:
		try:
			box["value"] = fn(*args, **kwargs)
		except BaseException as exc:  # noqa: BLE001 - we want everything
			box["error"] = exc
		finally:
			done.set()

	wx.CallAfter(_runner)

	if not done.wait(timeout=timeout):
		raise MainThreadCallTimeout(
			f"Main-thread call {getattr(fn, '__qualname__', fn)!r} timed out after {timeout}s"
		)

	if "error" in box:
		raise box["error"]
	return box["value"]  # type: ignore[return-value]