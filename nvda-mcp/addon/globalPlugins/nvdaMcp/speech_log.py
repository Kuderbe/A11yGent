# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
In-memory log of everything NVDA speaks.

We hook :data:`speech.extensions.pre_speech` (and, as a belt-and-suspenders
fallback, :data:`speech.extensions.pre_speechQueued`). Both fire when NVDA
is about to speak a :class:`speech.SpeechSequence`. A speech sequence is
an iterable mixing plain strings (the text NVDA will vocalise) with
:class:`speech.commands.SpeechCommand` objects (pitch changes, pauses,
language switches, …). We only care about the strings; concatenating them
gives us the same text a user sees in NVDA's Speech Viewer.

Handler lifetime — why a module-level function
----------------------------------------------
NVDA's ``extensionPoints.HandlerRegistrar.register`` stores handlers as
weak references. For a bound instance method (``self.on_pre_speech``)
it uses ``BoundMethodWeakref`` which holds ``weakref.ref(inst)`` and
``weakref.ref(func)``.

We used to register ``self._on_pre_speech`` and it looked correct, but
during add-on reloads / config profile switches multiple ``SpeechLog``
instances can exist, and NVDA's ``_handlers`` OrderedDict is keyed by
``(id(inst), id(func))`` — meaning two live instances with different
``id(inst)`` both register successfully but the second may replace no
one, and the first may die silently.

To eliminate this whole class of bugs we register a **module-level
function** as the handler. NVDA then uses ``AnnotatableWeakref`` on the
function, and the function itself lives forever (as long as this module
is imported). The active :class:`SpeechLog` is looked up via a module
global, which we swap on ``start()`` / ``stop()``.

The log is a bounded ring buffer, guarded by a :class:`threading.Lock` so
the MCP server thread can read from it while NVDA's main thread writes
new entries.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any, Deque, List, Optional

from . import config


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeechEntry:
	"""A single utterance recorded from NVDA."""

	#: Monotonically increasing id, unique within this plugin session.
	id: int
	#: Unix timestamp (seconds, float) when the utterance was queued.
	timestamp: float
	#: The concatenated spoken text (SpeechCommand objects stripped).
	text: str

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


def _extract_text(speech_sequence: Any) -> str:
	"""
	Turn a NVDA ``SpeechSequence`` into a plain string.

	Non-string items (``SpeechCommand`` instances such as pitch/rate
	changes) are silently dropped. Strings are joined with a single space
	to roughly mimic how the Speech Viewer renders them.
	"""
	if speech_sequence is None:
		return ""
	parts: List[str] = []
	try:
		iterator = iter(speech_sequence)
	except TypeError:
		return str(speech_sequence)
	for item in iterator:
		if isinstance(item, str):
			# NVDA sometimes emits empty separators; skip pure whitespace.
			s = item.strip()
			if s:
				parts.append(s)
	return " ".join(parts)


# ---------------------------------------------------------------------------
# Module-level handler + active-instance registry
# ---------------------------------------------------------------------------
#
# We keep exactly one "active" SpeechLog and route pre_speech events to it.
# This is the safest possible handler wrt NVDA's weakref-based registry:
# the function itself is a module-level object and lives for the whole
# Python process, so the AnnotatableWeakref inside NVDA never dies.

_active_speech_log: Optional["SpeechLog"] = None
_active_lock = threading.Lock()


def _dispatch_pre_speech(
	speechSequence: Any = None,
	symbolLevel: Any = None,
	priority: Any = None,
	**_: Any,
) -> None:
	"""
	Module-level handler for ``speech.extensions.pre_speech`` and
	``pre_speechQueued``. Routes the call to the currently-active
	:class:`SpeechLog` (if any).

	Signature accepts ``**_`` so future keyword arguments do not break us.
	NVDA uses ``callWithSupportedKwargs`` in ``Action.notify`` so extra
	kwargs are filtered anyway, but explicit ``**_`` costs nothing.
	"""
	sl = _active_speech_log
	if sl is None:
		return
	try:
		sl._record(speechSequence)
	except Exception:  # noqa: BLE001
		log.exception("nvda-mcp: _dispatch_pre_speech raised")


class SpeechLog:
	"""
	Thread-safe ring buffer of :class:`SpeechEntry` objects.

	Lifecycle:

	* :meth:`start` sets this instance as the active receiver and
	  registers the module-level ``_dispatch_pre_speech`` handler on
	  ``speech.extensions.pre_speech`` (and ``pre_speechQueued`` as
	  fallback) — but only if no other instance has already done so.
	* :meth:`stop`  clears the active receiver. The module-level
	  handler remains registered but becomes a no-op; this is fine
	  because it costs nothing and avoids race conditions with
	  concurrent register/unregister.

	Query API is designed so that agents can either poll the tail
	(``get_entries(limit=N)``) or resume from a known id
	(``get_entries(since_id=X)``).
	"""

	def __init__(self, maxlen: Optional[int] = None) -> None:
		self._maxlen = maxlen if maxlen is not None else config.SPEECH_LOG_MAX_ENTRIES
		self._entries: Deque[SpeechEntry] = deque(maxlen=self._maxlen)
		self._lock = threading.Lock()
		self._next_id = 1
		self._started = False
		# Public diagnostic counter polled by the /debug/status endpoint.
		self._pre_speech_calls = 0

	# --- Registration --------------------------------------------------------

	def start(self) -> None:
		global _active_speech_log
		if self._started:
			return
		# Import lazily so the module is testable outside NVDA.
		try:
			from speech import extensions as speech_extensions  # type: ignore
		except Exception:  # noqa: BLE001
			log.exception("nvda-mcp: cannot import speech.extensions")
			raise

		hooks_registered: List[str] = []
		for hook_name in ("pre_speech", "pre_speechQueued"):
			hook = getattr(speech_extensions, hook_name, None)
			if hook is None:
				log.warning(
					"nvda-mcp: speech.extensions.%s missing on this NVDA build",
					hook_name,
				)
				continue
			if not hasattr(hook, "register"):
				log.error(
					"nvda-mcp: speech.extensions.%s has no .register method "
					"(type=%s)", hook_name, type(hook).__name__,
				)
				continue
			# Best-effort: remove any stale registration of the same handler.
			# ``unregister`` returns False if there was nothing to remove;
			# it does not raise.
			try:
				hook.unregister(_dispatch_pre_speech)
			except Exception:  # noqa: BLE001
				pass
			hook.register(_dispatch_pre_speech)
			handler_count = len(getattr(hook, "_handlers", {}))
			hooks_registered.append(f"{hook_name}({handler_count})")

		if not hooks_registered:
			raise RuntimeError(
				"No usable speech extension point found on this NVDA build "
				"(tried pre_speech, pre_speechQueued)."
			)

		# Install ourselves as the active instance AFTER the hooks are up,
		# so we can't miss the first event.
		with _active_lock:
			previous = _active_speech_log
			_active_speech_log = self
		if previous is not None and previous is not self:
			log.warning(
				"nvda-mcp: another SpeechLog was already active (id=%s); "
				"replacing with id=%s", id(previous), id(self),
			)

		self._started = True
		log.info(
			"nvda-mcp: SpeechLog attached (maxlen=%d, self_id=%s, hooks=%s)",
			self._maxlen, id(self), ", ".join(hooks_registered),
		)

	def stop(self) -> None:
		global _active_speech_log
		if not self._started:
			return
		with _active_lock:
			if _active_speech_log is self:
				_active_speech_log = None
		self._started = False
		log.info(
			"nvda-mcp: SpeechLog detached (self_id=%s). Module-level "
			"handler remains registered as a no-op.",
			id(self),
		)

	# Public diagnostic properties, used by the /debug/status endpoint.
	@property
	def is_attached(self) -> bool:
		return self._started

	@property
	def is_active_receiver(self) -> bool:
		"""True iff this instance is the one that will receive pre_speech events."""
		return _active_speech_log is self

	@property
	def pre_speech_call_count(self) -> int:
		return self._pre_speech_calls

	@classmethod
	def diagnostics(cls) -> dict[str, Any]:
		"""
		Class-level diagnostic snapshot for the /debug/status endpoint.

		Reports the state of NVDA's own extension-point registrations,
		which is the ground truth for "is anyone hooked up".
		"""
		info: dict[str, Any] = {
			"active_speech_log_id": id(_active_speech_log) if _active_speech_log else None,
		}
		try:
			from speech import extensions as speech_extensions  # type: ignore
			for hook_name in ("pre_speech", "pre_speechQueued"):
				hook = getattr(speech_extensions, hook_name, None)
				if hook is None:
					info[f"{hook_name}_available"] = False
					continue
				handlers = getattr(hook, "_handlers", None)
				info[f"{hook_name}_available"] = True
				info[f"{hook_name}_handler_count"] = (
					len(handlers) if handlers is not None else None
				)
				# Check whether our specific module-level handler is in there.
				our_key = id(_dispatch_pre_speech)
				info[f"{hook_name}_our_handler_registered"] = (
					handlers is not None and our_key in handlers
				)
		except Exception as exc:  # noqa: BLE001
			info["extensions_error"] = repr(exc)
		return info

	# --- Write path (called on NVDA's main thread) ---------------------------

	def _record(self, speech_sequence: Any) -> None:
		"""
		Record one utterance. Called by :func:`_dispatch_pre_speech`.

		Kept as a separate method (not the direct handler) so that:
		1. NVDA registers a stable module-level function, not a bound method.
		2. We can still access ``self`` for the ring buffer + counter.
		"""
		self._pre_speech_calls += 1
		text = _extract_text(speech_sequence)
		if not text:
			# Log the first few "empty" utterances at INFO so we can
			# distinguish "hook never fires" from "hook fires but
			# extraction returns empty". After 5 we go quiet.
			if self._pre_speech_calls <= 5:
				log.info(
					"nvda-mcp: pre_speech fired (#%d) but no text extracted "
					"from sequence of type %s",
					self._pre_speech_calls,
					type(speech_sequence).__name__,
				)
			return
		with self._lock:
			entry = SpeechEntry(
				id=self._next_id, timestamp=time.time(), text=text,
			)
			self._next_id += 1
			self._entries.append(entry)
		# Log the first few utterances at INFO so we can prove in the
		# NVDA log that the hook is working, then go quiet.
		if self._next_id <= 6:
			log.info("nvda-mcp: captured speech #%d: %r", entry.id, text[:120])

	# --- Read path (called from MCP server thread) ---------------------------

	def get_entries(
		self,
		limit: int = 50,
		since_id: int = 0,
	) -> List[SpeechEntry]:
		"""
		Return recorded entries in chronological order.

		:param limit: maximum number of entries to return. Values <= 0 mean
			"return everything currently available".
		:param since_id: return only entries with ``id > since_id``.
		"""
		with self._lock:
			snapshot = list(self._entries)
		if since_id > 0:
			snapshot = [e for e in snapshot if e.id > since_id]
		if limit and limit > 0:
			snapshot = snapshot[-limit:]
		return snapshot

	def last_entry(self) -> Optional[SpeechEntry]:
		with self._lock:
			if not self._entries:
				return None
			return self._entries[-1]

	def clear(self) -> None:
		with self._lock:
			self._entries.clear()

	def __len__(self) -> int:  # pragma: no cover - trivial
		with self._lock:
			return len(self._entries)