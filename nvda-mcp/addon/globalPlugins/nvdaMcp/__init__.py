# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
NVDA MCP Bridge - global plugin entry point.

When NVDA loads this add-on it instantiates :class:`GlobalPlugin`, which:

1. Builds the shared :class:`ServerContext` (speech log + input backends + auth).
2. Starts the speech-log listener (``pre_speech`` extension point).
3. Starts the MCP HTTP server on a background thread if
   :data:`config.AUTO_START` is True.

On unload NVDA calls :meth:`GlobalPlugin.terminate`, which stops the server
and unregisters the listener in the reverse order.

Two optional scripts are exposed but bound to no gesture by default; users
can bind them from NVDA's Input Gestures dialog under the "MCP Bridge"
category:

* ``script_toggleMcpServer`` - start/stop the server on demand.
* ``script_showMcpStatus``   - speak the server URL and running state.
"""

from __future__ import annotations

import logging
from typing import Any

# NVDA-only imports. These are always available at runtime but not during
# static analysis on non-Windows dev machines - hence the type: ignore.
import globalPluginHandler  # type: ignore
import ui  # type: ignore
import scriptHandler  # type: ignore
try:
	import addonHandler  # type: ignore
	addonHandler.initTranslation()
except Exception:  # noqa: BLE001
	pass

from . import config
from .mcp_server import McpServerThread, build_default_context


log = logging.getLogger(__name__)

# Fire the moment this module is imported by NVDA's global plugin loader.
# If we don't see this line in the NVDA log, the plugin is not loading
# at all - almost certainly a manifest / installation issue.
log.info(
	"nvda-mcp: module imported (config: host=%s port=%s path=%s auto_start=%s)",
	config.MCP_HOST, config.MCP_PORT, config.MCP_PATH, config.AUTO_START,
)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""NVDA global plugin that exposes speech + input over MCP."""

	# Advertised category name in the Input Gestures dialog.
	scriptCategory = "MCP Bridge"

	# Class-level counter to detect multiple __init__ calls in the same
	# Python process. If this ever climbs past 1 we know NVDA reloaded
	# the plugin (config profile switch, /debug/status will then show a
	# different speech_log.self_id from the one whose handler is
	# registered in NVDA).
	_init_counter: int = 0

	def __init__(self) -> None:
		GlobalPlugin._init_counter += 1
		log.info(
			"nvda-mcp: GlobalPlugin.__init__ start (init_counter=%d)",
			GlobalPlugin._init_counter,
		)
		if GlobalPlugin._init_counter > 1:
			log.warning(
				"nvda-mcp: GlobalPlugin has been instantiated %d times in this "
				"Python process. Prior SpeechLog instances may still hold "
				"pre_speech registrations; module-level dispatch handles this "
				"but check /debug/status if speech capture misbehaves.",
				GlobalPlugin._init_counter,
			)
		super().__init__()
		self._ctx = build_default_context()
		self._server = McpServerThread(self._ctx)
		# Start capturing speech immediately so we do not miss anything
		# spoken before the first MCP client connects.
		try:
			self._ctx.speech_log.start()
		except Exception:  # noqa: BLE001
			log.exception("nvda-mcp: failed to attach speech listener")

		if config.AUTO_START:
			try:
				self._server.start()
			except Exception:  # noqa: BLE001
				log.exception("nvda-mcp: failed to auto-start MCP server")

		log.info(
			"nvda-mcp: global plugin initialised "
			"(auto_start=%s, endpoint=http://%s:%s%s, speech_attached=%s)",
			config.AUTO_START, config.MCP_HOST, config.MCP_PORT, config.MCP_PATH,
			self._ctx.speech_log.is_attached,
		)

	def terminate(self) -> None:
		try:
			self._server.stop()
		except Exception:  # noqa: BLE001
			log.exception("nvda-mcp: error while stopping MCP server")
		try:
			self._ctx.speech_log.stop()
		except Exception:  # noqa: BLE001
			log.exception("nvda-mcp: error while detaching speech listener")
		try:
			super().terminate()
		except Exception:  # noqa: BLE001
			pass

	# ------------------------------------------------------------------ #
	# Scripts (bindable via Input Gestures dialog)                       #
	# ------------------------------------------------------------------ #

	@scriptHandler.script(
		description="Toggle the NVDA MCP Bridge server on or off.",
		category="MCP Bridge",
	)
	def script_toggleMcpServer(self, gesture: Any) -> None:  # noqa: N802
		if self._server.is_running():
			self._server.stop()
			ui.message("MCP Bridge server stopped")
		else:
			self._server.start()
			ui.message(
				f"MCP Bridge server started on {config.MCP_HOST} port {config.MCP_PORT}"
			)

	@scriptHandler.script(
		description="Report the NVDA MCP Bridge server status and URL.",
		category="MCP Bridge",
	)
	def script_showMcpStatus(self, gesture: Any) -> None:  # noqa: N802
		state = "running" if self._server.is_running() else "stopped"
		url = f"http://{config.MCP_HOST}:{config.MCP_PORT}{config.MCP_PATH}"
		ui.message(f"MCP Bridge {state} at {url}")