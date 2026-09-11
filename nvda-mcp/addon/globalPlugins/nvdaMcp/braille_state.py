# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
In-memory snapshot of the current NVDA braille output.

We hook NVDA's ``pre_writeCells`` extension point, which fires every time
NVDA is about to write a row of cells to the braille display. Its location
differs by NVDA version (both are the same object with the same signature):

* NVDA 2025+: ``braille.extensions.pre_writeCells`` (``braille`` is a
  package; see ``nvda/source/braille/extensions.py``).
* NVDA 2024.3 and earlier: ``braille.pre_writeCells`` (``braille`` is a
  flat module). We resolve whichever exists via
  :func:`_resolve_pre_writeCells_hook`.

Callback signature:

    handler(cells: list[int], rawText: str, currentCellCount: int)

* ``cells``: list of ints, one per braille cell. Each int is an 8-bit
  dot pattern (bits 0-7 = dots 1-8). Range 0..255. Converts to Unicode
  Braille Patterns via ``chr(0x2800 + cell)`` (U+2800 .. U+28FF).
* ``rawText``: the source string that produced those cells, before
  translation to the braille table. This is what NVDA's own Braille
  Viewer window renders in its raw-text row.
* ``currentCellCount``: the number of cells NVDA is currently rendering
  to (may be limited by ``filter_displayDimensions``).

Unlike speech, braille is inherently *state* rather than *stream*: at any
moment there is exactly one row of cells that the user is feeling. So
this module keeps the **latest** update only (no ring buffer, no ids).
The MCP tool ``get_braille_state`` returns that snapshot.

Handler lifetime: why a module-level function
----------------------------------------------
Same rationale as :mod:`speech_log`: NVDA's
``extensionPoints.HandlerRegistrar.register`` stores handlers as weak
references keyed by ``(id(inst), id(func))``. Registering a bound
method risks silent orphaning after an add-on reload. We register a
module-level function and swap the "active receiver" via a module
global.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional


log = logging.getLogger(__name__)


#: Start of the Unicode Braille Patterns block. ``chr(BRAILLE_UNICODE_BASE + cell)``
#: yields the visual glyph for an 8-dot cell value 0..255.
BRAILLE_UNICODE_BASE = 0x2800


@dataclass
class BrailleSnapshot:
	"""A single row of braille cells currently shown to the user."""

	#: 8-bit cell values (one entry per cell, range 0..255).
	cells: List[int] = field(default_factory=list)
	#: Same cells rendered as Unicode Braille Patterns (one char per cell).
	braille_unicode: str = ""
	#: The raw source text that produced these cells (before table translation).
	raw_text: str = ""
	#: Number of cells NVDA thinks the display has right now.
	cell_count: int = 0
	#: Unix timestamp of the last update, or ``None`` if never updated.
	timestamp: Optional[float] = None
	#: Braille display name (e.g. ``"noBraille"`` if no physical display is connected).
	display_name: str = ""
	#: Nominal display size as reported by ``braille.handler.displaySize``.
	display_size: int = 0

	def to_dict(self) -> dict[str, Any]:
		return {
			"cells": list(self.cells),
			"braille_unicode": self.braille_unicode,
			"raw_text": self.raw_text,
			"cell_count": self.cell_count,
			"timestamp": self.timestamp,
			"display": {
				"name": self.display_name,
				"size": self.display_size,
			},
		}


def _cells_to_unicode(cells: List[int]) -> str:
	"""Convert an iterable of 8-bit cell values to a Unicode braille string."""
	try:
		return "".join(
			chr(BRAILLE_UNICODE_BASE + (int(c) & 0xFF)) for c in cells
		)
	except Exception:  # noqa: BLE001
		# Extremely defensive: if a driver ever yields something weird
		# (e.g. numpy scalars), fall back to a safe representation.
		return ""


# ---------------------------------------------------------------------------
# Module-level handler + active-instance registry
# ---------------------------------------------------------------------------

_active_braille_state: Optional["BrailleState"] = None
_active_lock = threading.Lock()


def _resolve_pre_writeCells_hook() -> tuple[Any, str]:
	"""
	Locate NVDA's ``pre_writeCells`` extension point across NVDA versions.

	The extension point moved between NVDA releases:

	* **NVDA 2025+**: ``braille`` is a package and the action lives at
	  ``braille.extensions.pre_writeCells`` (commit 54ccd097f,
	  "refactor(braille): split braille.py into a package", #20252).
	* **NVDA 2024.3 and earlier**: ``braille`` is a flat module and the
	  same action is an attribute on the module itself:
	  ``braille.pre_writeCells`` (defined near line 2006 of
	  ``source/braille.py``, fired near line 2402).

	The action object and its notify signature
	``(cells, rawText, currentCellCount)`` are identical in both layouts;
	only the import path differs.

	Returns ``(hook, source_label)`` where ``hook`` is the extension-point
	object (has ``.register`` / ``.unregister``) and ``source_label`` is a
	human-readable location string. On failure returns ``(None, error)``.
	"""
	# Newest layout first: braille.extensions.pre_writeCells (2025+).
	try:
		from braille import extensions as braille_extensions  # type: ignore

		hook = getattr(braille_extensions, "pre_writeCells", None)
		if hook is not None and hasattr(hook, "register"):
			return hook, "braille.extensions.pre_writeCells"
	except Exception:  # noqa: BLE001
		# Package import failed (flat-module NVDA) or attribute missing;
		# fall through to the legacy location.
		pass

	# Legacy flat module: braille.pre_writeCells (2024.3 and earlier).
	try:
		import braille  # type: ignore

		hook = getattr(braille, "pre_writeCells", None)
		if hook is not None and hasattr(hook, "register"):
			return hook, "braille.pre_writeCells"
	except Exception as exc:  # noqa: BLE001
		return None, "import_error: %r" % (exc,)

	return None, "pre_writeCells not found on braille.extensions or braille"


def _dispatch_pre_write_cells(
	cells: Any = None,
	rawText: str = "",
	currentCellCount: int = 0,
	**_: Any,
) -> None:
	"""
	Module-level handler for ``braille.extensions.pre_writeCells``.

	Routes the call to the currently-active :class:`BrailleState` (if any).
	Signature accepts ``**_`` so future keyword arguments do not break us.
	NVDA uses ``callWithSupportedKwargs`` in ``Action.notify`` and would
	filter them anyway, but explicit ``**_`` costs nothing.
	"""
	bs = _active_braille_state
	if bs is None:
		return
	try:
		bs._record(cells or [], rawText or "", int(currentCellCount or 0))
	except Exception:  # noqa: BLE001
		log.exception("nvda-mcp: _dispatch_pre_write_cells raised")


class BrailleState:
	"""
	Thread-safe holder of the most recent braille output.

	Lifecycle:

	* :meth:`start` sets this instance as the active receiver and
	  registers the module-level ``_dispatch_pre_write_cells`` handler
	  on ``braille.extensions.pre_writeCells``.
	* :meth:`stop`  clears the active receiver. The module-level handler
	  remains registered but becomes a no-op. Same trade-off as
	  :class:`speech_log.SpeechLog`.

	Query API is a single ``current()`` that returns a full snapshot dict.
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._snapshot = BrailleSnapshot()
		self._started = False
		#: Public diagnostic counter polled by ``/debug/status``.
		self._pre_write_cells_calls = 0

	# --- Registration --------------------------------------------------------

	def start(self) -> None:
		global _active_braille_state
		if self._started:
			return
		# Resolve the pre_writeCells extension point across NVDA versions
		# (braille.extensions.pre_writeCells on 2025+, braille.pre_writeCells
		# on 2024.3 and earlier). See _resolve_pre_writeCells_hook.
		hook, source = _resolve_pre_writeCells_hook()
		if hook is None:
			raise RuntimeError(
				"pre_writeCells is not available on this NVDA build "
				"(%s)." % (source,)
			)

		# Best-effort: remove any stale registration of the same handler.
		try:
			hook.unregister(_dispatch_pre_write_cells)
		except Exception:  # noqa: BLE001
			pass
		hook.register(_dispatch_pre_write_cells)
		handler_count = len(getattr(hook, "_handlers", {}) or {})

		# Prime the snapshot with the current display metadata, so a client
		# calling get_braille_state before NVDA has written anything still
		# gets a non-empty display block.
		self._refresh_display_metadata()

		with _active_lock:
			previous = _active_braille_state
			_active_braille_state = self
		if previous is not None and previous is not self:
			log.warning(
				"nvda-mcp: another BrailleState was already active (id=%s); "
				"replacing with id=%s", id(previous), id(self),
			)

		self._started = True
		log.info(
			"nvda-mcp: BrailleState attached (self_id=%s, source=%s, "
			"pre_writeCells handler_count=%d, display=%r size=%d)",
			id(self), source, handler_count,
			self._snapshot.display_name, self._snapshot.display_size,
		)

	def stop(self) -> None:
		global _active_braille_state
		if not self._started:
			return
		with _active_lock:
			if _active_braille_state is self:
				_active_braille_state = None
		self._started = False
		log.info(
			"nvda-mcp: BrailleState detached (self_id=%s). Module-level "
			"handler remains registered as a no-op.",
			id(self),
		)

	# --- Diagnostic properties ---------------------------------------------

	@property
	def is_attached(self) -> bool:
		return self._started

	@property
	def is_active_receiver(self) -> bool:
		return _active_braille_state is self

	@property
	def pre_write_cells_call_count(self) -> int:
		return self._pre_write_cells_calls

	@classmethod
	def diagnostics(cls) -> dict[str, Any]:
		"""
		Class-level diagnostic snapshot for the /debug/status endpoint.
		Reports NVDA's own extension-point registrations.
		"""
		info: dict[str, Any] = {
			"active_braille_state_id": (
				id(_active_braille_state) if _active_braille_state else None
			),
		}
		# Resolve pre_writeCells across NVDA versions (2025+ package layout
		# and 2024.3 flat-module layout). Report which location we found.
		hook, source = _resolve_pre_writeCells_hook()
		info["pre_writeCells_source"] = source
		if hook is None:
			info["pre_writeCells_available"] = False
		else:
			handlers = getattr(hook, "_handlers", None)
			info["pre_writeCells_available"] = True
			info["pre_writeCells_handler_count"] = (
				len(handlers) if handlers is not None else None
			)
			our_key = id(_dispatch_pre_write_cells)
			info["pre_writeCells_our_handler_registered"] = (
				handlers is not None and our_key in handlers
			)
		return info

	# --- Write path (called on NVDA's main thread) --------------------------

	def _record(self, cells: Any, raw_text: str, cell_count: int) -> None:
		"""Record the latest braille write. Called by :func:`_dispatch_pre_write_cells`."""
		self._pre_write_cells_calls += 1
		# Normalise cells to a plain list[int]. Drivers may pass tuples,
		# arrays, or generators.
		try:
			cell_list: List[int] = [int(c) & 0xFF for c in cells]
		except Exception:  # noqa: BLE001
			cell_list = []
		unicode_repr = _cells_to_unicode(cell_list)
		# Refresh display metadata cheaply. We do this here (NVDA's main
		# thread) rather than in current() (MCP server thread) so no
		# thread-marshalling is needed on read.
		display_name, display_size = self._probe_display_info()
		with self._lock:
			self._snapshot = BrailleSnapshot(
				cells=cell_list,
				braille_unicode=unicode_repr,
				raw_text=raw_text or "",
				cell_count=int(cell_count) if cell_count else len(cell_list),
				timestamp=time.time(),
				display_name=display_name,
				display_size=display_size,
			)
		# Log the first few writes at INFO so we can prove in the NVDA log
		# that the hook is working, then go quiet.
		if self._pre_write_cells_calls <= 5:
			log.info(
				"nvda-mcp: captured braille write #%d: %d cells, raw=%r",
				self._pre_write_cells_calls, len(cell_list), raw_text[:120],
			)

	def _refresh_display_metadata(self) -> None:
		"""Poll ``braille.handler`` for display name / size and cache them."""
		display_name, display_size = self._probe_display_info()
		with self._lock:
			# Preserve existing cells/text; only refresh metadata.
			self._snapshot.display_name = display_name
			self._snapshot.display_size = display_size

	@staticmethod
	def _probe_display_info() -> tuple[str, int]:
		"""Return ``(display_name, display_size)`` from ``braille.handler``, or safe defaults."""
		try:
			import braille  # type: ignore
			handler = getattr(braille, "handler", None)
			if handler is None:
				return "", 0
			size = int(getattr(handler, "displaySize", 0) or 0)
			display = getattr(handler, "display", None)
			if display is None:
				return "", size
			# ``description`` is a human-readable name (e.g. "No braille"),
			# ``name`` is the driver id (e.g. "noBraille").
			name = (
				getattr(display, "description", None)
				or getattr(display, "name", None)
				or ""
			)
			return str(name), size
		except Exception:  # noqa: BLE001
			return "", 0

	# --- Read path (called from MCP server thread) --------------------------

	def current(self) -> dict[str, Any]:
		"""Return a snapshot dict of the current braille output."""
		with self._lock:
			return self._snapshot.to_dict()