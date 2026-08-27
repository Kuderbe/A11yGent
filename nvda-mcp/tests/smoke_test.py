# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
Smoke test for the NVDA MCP Bridge add-on.

Run this on the Windows machine where NVDA is running with the add-on
installed. It exercises every v1 tool and prints bespoke diagnostics if
something goes wrong.

Usage::

	python -m pip install "mcp>=2.0,<3.0"       # one-time client-side install
	python tests\\smoke_test.py                  # everything except key injection
	python tests\\smoke_test.py --send-keys      # includes Notepad typing test
	python tests\\smoke_test.py --verbose --port 9000

Why the official ``mcp`` SDK client?
------------------------------------
The add-on's *server* side is stdlib-only (no third-party deps at
NVDA runtime — see mcp_server.py). The *test* side deliberately
uses the official Anthropic ``mcp`` Python SDK to prove that the
server is **spec-compliant**: if the reference client can drive it,
so can Claude Desktop, Cline, or any other MCP client. This is a
much stronger correctness check than hitting the JSON-RPC endpoint
with hand-rolled ``urllib`` calls.

Exit codes
----------
	0   All checks passed.
	1   Server unreachable (network / process).
	2   MCP handshake failed.
	3   A tool call returned an error.
	4   Keyboard-injection step failed.
	10  ``mcp`` client library not installed in this Python environment.
	20  Interrupted by user (Ctrl+C).
	99  Unexpected error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import sys
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest


# ---------------------------------------------------------------------------
# Constants matching addon/globalPlugins/nvdaMcp/config.py defaults.
# ---------------------------------------------------------------------------

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_PATH = "/mcp"

EXPECTED_TOOLS = {
	"get_speech_log",
	"get_last_spoken",
	"clear_speech_log",
	"send_key",
	"send_keys",
	"type_text",
	"get_focus_info",
	"get_server_info",
}

REPORT_FILENAME = "smoke_test_report.txt"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

class Report:
	"""Tee everything we print to stdout AND to a report file."""

	def __init__(self, path: str) -> None:
		self.path = path
		self._fh = open(path, "w", encoding="utf-8")
		self._results: List[Tuple[str, bool, str]] = []

	def close(self) -> None:
		try:
			self._fh.close()
		except Exception:  # noqa: BLE001
			pass

	def _write(self, text: str) -> None:
		try:
			self._fh.write(text + "\n")
			self._fh.flush()
		except Exception:  # noqa: BLE001
			pass

	# --- Levels -------------------------------------------------------------

	def banner(self, step: int, title: str) -> None:
		line = f"\n=== [{step}] {title} " + "=" * max(1, 60 - len(title))
		print(line)
		self._write(line)

	def info(self, msg: str) -> None:
		print(f"    {msg}")
		self._write(f"    {msg}")

	def ok(self, msg: str) -> None:
		print(f"  \u2713 {msg}")
		self._write(f"  [OK]   {msg}")

	def warn(self, msg: str) -> None:
		print(f"  ! {msg}")
		self._write(f"  [WARN] {msg}")

	def fail(self, msg: str) -> None:
		print(f"  \u2717 {msg}")
		self._write(f"  [FAIL] {msg}")

	def record(self, name: str, passed: bool, detail: str = "") -> None:
		self._results.append((name, passed, detail))

	def summary(self) -> bool:
		self.banner(99, "Summary")
		width = max((len(n) for n, _, _ in self._results), default=10)
		all_ok = True
		for name, passed, detail in self._results:
			marker = "PASS" if passed else "FAIL"
			line = f"  {name.ljust(width)}  {marker}"
			if detail and not passed:
				line += f"  -- {detail}"
			print(line)
			self._write(line)
			all_ok = all_ok and passed
		self.info(f"Full log written to: {self.path}")
		return all_ok


# ---------------------------------------------------------------------------
# NVDA-specific diagnostics
# ---------------------------------------------------------------------------

def _nvda_log_hint(report: Report) -> None:
	"""Print the standard location of NVDA's log to check for plugin errors."""
	appdata = os.environ.get("APPDATA", "%APPDATA%")
	report.info(f"Check the NVDA log for tracebacks: {appdata}\\nvda\\nvda.log")
	report.info("Set NVDA logging to 'debug' via NVDA menu > Preferences > Settings > General")


def _dump_env(report: Report) -> None:
	report.info(f"Python:   {sys.version.split()[0]} ({sys.executable})")
	report.info(f"Platform: {platform.platform()}")
	report.info(f"CWD:      {os.getcwd()}")


# ---------------------------------------------------------------------------
# Raw HTTP reachability probe (uses stdlib only - runs before we touch mcp)
# ---------------------------------------------------------------------------

def probe_endpoint(
	host: str, port: int, path: str, report: Report, verbose: bool
) -> bool:
	"""Return True if the MCP endpoint is at least reachable at the TCP level."""
	url = f"http://{host}:{port}{path}"
	health_url = f"http://{host}:{port}/health"
	report.info(f"Probing {url}")

	# 1) Bare TCP connect - cheapest way to distinguish "nothing listening"
	#    from "listening but rejects HTTP".
	try:
		with socket.create_connection((host, port), timeout=3.0):
			pass
	except ConnectionRefusedError:
		report.fail("TCP connection refused - nothing is listening on that port.")
		report.info("Likely causes (in order of probability):")
		report.info("  1) NVDA is not running.")
		report.info("  2) The nvdaMcp add-on is not installed or was disabled.")
		report.info("  3) The add-on failed to load - see NVDA log.")
		report.info("  4) config.AUTO_START is False; toggle the MCP server on")
		report.info("     from NVDA's Input Gestures dialog ('MCP Bridge' category).")
		report.info(f"  5) The port ({port}) is different from config.MCP_PORT.")
		_nvda_log_hint(report)
		return False
	except socket.timeout:
		report.fail(f"TCP connect to {host}:{port} timed out.")
		report.info("Likely a Windows Firewall inbound block or wrong host.")
		return False
	except OSError as exc:
		report.fail(f"TCP connect failed: {exc}")
		if verbose:
			report.info(traceback.format_exc())
		return False

	# 2) Try the /health endpoint - that's the cleanest liveness check.
	try:
		req = urlrequest.Request(health_url, method="GET")
		with urlrequest.urlopen(req, timeout=5.0) as resp:
			body = resp.read(200)
			if resp.status == 200:
				try:
					payload = json.loads(body.decode("utf-8"))
				except Exception:  # noqa: BLE001
					payload = None
				if isinstance(payload, dict) and payload.get("status") == "ok":
					report.ok("GET /health returned status=ok (HTTP 200).")
					return True
				report.ok(f"GET /health returned HTTP 200 but unexpected body: {body!r}")
				return True
			report.warn(f"GET /health returned HTTP {resp.status}: {body!r}")
			return True
	except urlerror.HTTPError as exc:
		# Any HTTP status back is *good news* - the HTTP server is there.
		report.ok(f"GET /health returned HTTP {exc.code} (server is up).")
		return True
	except urlerror.URLError as exc:
		report.fail(f"HTTP request failed: {exc}")
		report.info("Something is listening on the port but is not speaking HTTP.")
		return False
	except Exception as exc:  # noqa: BLE001
		report.fail(f"Unexpected error probing endpoint: {exc}")
		if verbose:
			report.info(traceback.format_exc())
		return False


# ---------------------------------------------------------------------------
# MCP client adapter (uses the official ``mcp`` SDK, v2 preferred, v1 fallback)
# ---------------------------------------------------------------------------

class ClientAdapter:
	"""
	Thin async wrapper over the official ``mcp`` Python SDK.

	Prefers the v2 ``mcp.Client`` one-liner, falls back to the v1
	``ClientSession`` + ``streamablehttp_client`` combination. Everything
	the smoke test needs is exposed here so the test steps don't have to
	branch on SDK version.
	"""

	def __init__(self, url: str) -> None:
		self.url = url
		self._backend: str = ""
		# v2 state
		self._v2_client: Any = None
		# v1 state
		self._v1_streams_cm: Any = None
		self._v1_session_cm: Any = None
		self._v1_session: Any = None

	@property
	def backend(self) -> str:
		return self._backend

	async def __aenter__(self) -> "ClientAdapter":
		await self._open()
		return self

	async def __aexit__(self, *exc: Any) -> None:
		await self.aclose()

	async def _open(self) -> None:
		# Try v2 first ("Client is one class").
		v2_exc: Optional[BaseException] = None
		try:
			from mcp import Client  # type: ignore
			self._backend = "mcp-v2"
			self._v2_client = Client(self.url)
			await self._v2_client.__aenter__()
			return
		except Exception as exc:  # noqa: BLE001
			v2_exc = exc

		# Fall back to v1 (ClientSession + streamable_http transport).
		try:
			from mcp import ClientSession  # type: ignore
			try:
				from mcp.client.streamable_http import streamablehttp_client  # type: ignore
			except ImportError:
				# Older intermediate v1.x releases named it differently.
				from mcp.client.streamable_http import (  # type: ignore
					streamable_http_client as streamablehttp_client,
				)
			self._backend = "mcp-v1"
			self._v1_streams_cm = streamablehttp_client(self.url)
			streams = await self._v1_streams_cm.__aenter__()
			read_stream, write_stream = streams[0], streams[1]
			self._v1_session_cm = ClientSession(read_stream, write_stream)
			self._v1_session = await self._v1_session_cm.__aenter__()
			await self._v1_session.initialize()
			return
		except Exception as v1_exc:  # noqa: BLE001
			raise RuntimeError(
				"Could not open an MCP session with the official mcp SDK. "
				f"v2 attempt raised: {v2_exc!r}; "
				f"v1 attempt raised: {v1_exc!r}"
			)

	async def aclose(self) -> None:
		if self._backend == "mcp-v2" and self._v2_client is not None:
			try:
				await self._v2_client.__aexit__(None, None, None)
			except Exception:  # noqa: BLE001
				pass
			self._v2_client = None
		elif self._backend == "mcp-v1":
			for cm_name in ("_v1_session_cm", "_v1_streams_cm"):
				cm = getattr(self, cm_name)
				if cm is not None:
					try:
						await cm.__aexit__(None, None, None)
					except Exception:  # noqa: BLE001
						pass
					setattr(self, cm_name, None)
			self._v1_session = None

	# --- MCP surface -----------------------------------------------------

	async def server_info(self) -> Dict[str, Any]:
		"""
		Best-effort extraction of {name, version} from whatever the SDK
		exposes after handshake. Both v1 and v2 store this in slightly
		different places; we probe a handful of well-known attributes.
		"""
		obj = self._v2_client if self._backend == "mcp-v2" else self._v1_session
		if obj is None:
			return {"name": None, "version": None}
		for attr in ("server_info", "serverInfo", "initialize_result",
		             "_init_result", "_initialize_result"):
			val = getattr(obj, attr, None)
			if val is None:
				continue
			# The attribute may itself be a pydantic model with a nested
			# serverInfo field. Try both flat and nested.
			name = getattr(val, "name", None)
			version = getattr(val, "version", None)
			if name is None:
				inner = getattr(val, "serverInfo", None) or getattr(val, "server_info", None)
				if inner is not None:
					name = getattr(inner, "name", None)
					version = getattr(inner, "version", None)
			if name is not None or version is not None:
				return {"name": name, "version": version}
		return {"name": None, "version": None}

	async def list_tools(self) -> List[Dict[str, Any]]:
		if self._backend == "mcp-v2":
			result = await self._v2_client.list_tools()
			seq = getattr(result, "tools", None) or result
		else:
			result = await self._v1_session.list_tools()
			seq = result.tools
		out: List[Dict[str, Any]] = []
		for t in seq:
			name = getattr(t, "name", None)
			if name is None and isinstance(t, dict):
				name = t.get("name")
			out.append({"name": name})
		return out

	async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None) -> Any:
		args = args or {}
		if self._backend == "mcp-v2":
			raw = await self._v2_client.call_tool(name, args)
		else:
			raw = await self._v1_session.call_tool(name, args)
		if _is_error_result(raw):
			raise RuntimeError(f"Tool {name!r} returned error: {raw!r}")
		return _extract_tool_result(raw)


def _is_error_result(result: Any) -> bool:
	"""Detect the isError / is_error flag (v1 camelCase, v2 snake_case)."""
	for attr in ("is_error", "isError"):
		if getattr(result, attr, False):
			return True
	if isinstance(result, dict):
		return bool(result.get("isError") or result.get("is_error"))
	return False


def _extract_tool_result(result: Any) -> Any:
	"""
	Turn a v1 ``CallToolResult`` or v2 tool return into a plain Python object.

	Prefers ``structured_content`` / ``structuredContent`` when present.
	Otherwise walks ``content`` and JSON-decodes the first text block.
	Falls back to the raw object.
	"""
	for attr in ("structured_content", "structuredContent"):
		val = getattr(result, attr, None)
		if val is not None:
			return val
		if isinstance(result, dict) and result.get(attr) is not None:
			return result[attr]

	content = getattr(result, "content", None)
	if content is None and isinstance(result, dict):
		content = result.get("content")
	if content:
		for block in content:
			text = getattr(block, "text", None)
			if text is None and isinstance(block, dict):
				text = block.get("text")
			if text is None:
				continue
			try:
				return json.loads(text)
			except Exception:  # noqa: BLE001
				return text
	if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
		return result
	return result


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------

def import_mcp_or_die(report: Report) -> None:
	"""Verify that the ``mcp`` client SDK is importable."""
	try:
		import mcp  # noqa: F401
	except ImportError as exc:
		report.fail(f"Cannot import the 'mcp' client library: {exc}")
		report.info("The smoke test uses the official Anthropic MCP SDK as its")
		report.info("client, to verify that the server is spec-compliant.")
		report.info("Install it into THIS Python (the one running smoke_test.py):")
		report.info(f'    "{sys.executable}" -m pip install "mcp>=2.0,<3.0"')
		report.info("Note: this is only needed on the client side. The add-on")
		report.info("itself has zero third-party dependencies.")
		report.summary()
		sys.exit(10)

	have_v2 = False
	have_v1 = False
	try:
		from mcp import Client  # noqa: F401
		have_v2 = True
	except Exception:  # noqa: BLE001
		pass
	try:
		from mcp import ClientSession  # noqa: F401
		from mcp.client import streamable_http  # noqa: F401
		have_v1 = True
	except Exception:  # noqa: BLE001
		pass

	if not (have_v2 or have_v1):
		report.fail(
			"'mcp' is importable but neither v2 'Client' nor v1 'ClientSession + "
			"streamable_http' surfaces are present."
		)
		report.info("Please pin a supported version:")
		report.info(f'    "{sys.executable}" -m pip install "mcp>=2.0,<3.0"')
		report.summary()
		sys.exit(10)

	if have_v2:
		report.ok("mcp v2 'Client' API detected (preferred).")
	else:
		report.ok("mcp v1 'ClientSession' API detected (v2 preferred, but v1 works).")


@contextmanager
def _timing(report: Report, label: str):
	t0 = time.perf_counter()
	yield
	dt = (time.perf_counter() - t0) * 1000
	report.info(f"({label} took {dt:.0f} ms)")


async def run_mcp_tests(  # noqa: C901 - explicitness > brevity here
	url: str,
	report: Report,
	verbose: bool,
	do_send_keys: bool,
) -> Tuple[bool, bool]:
	"""
	Returns (handshake_ok, all_tool_calls_ok).
	"""
	handshake_ok = False
	all_tools_ok = True

	try:
		async with ClientAdapter(url) as client:
			report.info(f"MCP client backend: {client.backend}")

			# --- 3. Handshake ---------------------------------------
			report.banner(3, "MCP handshake (initialize)")
			try:
				with _timing(report, "initialize"):
					info = await client.server_info()
				report.ok(
					f"Server: name={info.get('name')!r} "
					f"version={info.get('version')!r}"
				)
				handshake_ok = True
				report.record("handshake", True)
			except Exception as exc:  # noqa: BLE001
				report.fail(f"initialize() raised: {exc}")
				if verbose:
					report.info(traceback.format_exc())
				report.record("handshake", False, str(exc))
				_nvda_log_hint(report)
				return False, False

			# --- 4. Tool inventory ----------------------------------
			report.banner(4, "List tools (tools/list)")
			try:
				tools = await client.list_tools()
				tool_names = {t["name"] for t in tools if t.get("name")}
				report.info(f"Server advertises {len(tool_names)} tool(s): {sorted(tool_names)}")
				missing = EXPECTED_TOOLS - tool_names
				if missing:
					report.fail(f"Missing expected tools: {sorted(missing)}")
					report.record("tool_inventory", False, f"missing={sorted(missing)}")
					all_tools_ok = False
				else:
					report.ok("All expected tools are present.")
					report.record("tool_inventory", True)
			except Exception as exc:  # noqa: BLE001
				report.fail(f"list_tools() raised: {exc}")
				if verbose:
					report.info(traceback.format_exc())
				report.record("tool_inventory", False, str(exc))
				all_tools_ok = False

			# Helper closure ------------------------------------------
			async def call(name: str, args: Optional[Dict[str, Any]] = None) -> Any:
				args = args or {}
				if verbose:
					report.info(f"-> call_tool({name!r}, {args!r})")
				payload = await client.call_tool(name, args)
				if verbose:
					report.info(f"<- {payload!r}")
				return payload

			# --- 5. get_server_info ---------------------------------
			report.banner(5, "get_server_info")
			try:
				info = await call("get_server_info")
				report.ok(f"Server info: {info}")
				report.record("get_server_info", True)
			except Exception as exc:  # noqa: BLE001
				report.fail(f"{exc}")
				report.record("get_server_info", False, str(exc))
				all_tools_ok = False

			# --- 6. Speech log --------------------------------------
			report.banner(6, "Speech log")
			try:
				await call("clear_speech_log")
				report.info("Cleared speech log.")
				report.info(
					"Please make NVDA speak something in the next 15 s "
					"(NVDA+t, Alt-Tab, arrow keys in a menu, ...). "
					"Polling every 0.5 s."
				)

				# Poll for up to 15 s. Break out as soon as we see any entry.
				entries: List[Dict[str, Any]] = []
				count = 0
				poll_interval = 0.5
				max_polls = 30  # 30 * 0.5s = 15 s
				for _ in range(max_polls):
					await asyncio.sleep(poll_interval)
					result = await call("get_speech_log", {"limit": 20})
					if not isinstance(result, dict):
						raise RuntimeError(
							f"Expected object, got {type(result).__name__}: {result!r}"
						)
					entries = result.get("entries", [])
					if not isinstance(entries, list):
						raise RuntimeError(
							f"'entries' must be a list, got {type(entries).__name__}"
						)
					count = result.get("count", len(entries))
					if entries:
						break

				if not entries:
					report.warn(
						"Speech log is empty after 15 s. Either NVDA did not "
						"speak in the window, or the pre_speech hook is not "
						"attached."
					)
					# Fetch the server-side debug status so we can diagnose
					# why the buffer stayed empty.
					debug_url = url.rsplit("/", 1)[0] + "/debug/status"
					debug_url = debug_url.replace("/mcp/debug", "/debug")
					# Simpler: derive from host/port args directly.
					host_port = url.split("//", 1)[1].split("/", 1)[0]
					debug_url = f"http://{host_port}/debug/status"
					report.info(f"Fetching diagnostics from {debug_url} ...")
					try:
						req = urlrequest.Request(debug_url, method="GET")
						with urlrequest.urlopen(req, timeout=5.0) as resp:
							debug_body = resp.read().decode("utf-8")
						debug_data = json.loads(debug_body)
						report.info(f"/debug/status: {json.dumps(debug_data, indent=2)}")
						sl = debug_data.get("speech_log", {})
						attached = sl.get("listener_attached")
						calls = sl.get("pre_speech_call_count", 0)
						if attached is False:
							report.info(
								"DIAGNOSIS: pre_speech listener was never attached "
								"(SpeechLog.start() failed or was not called). "
								"Check the NVDA log for a traceback from nvda-mcp."
							)
						elif attached and calls == 0:
							report.info(
								"DIAGNOSIS: pre_speech listener is attached but has "
								"never fired (0 calls). NVDA speech extension point "
								"may not be delivering events to us. Check that the "
								"add-on is enabled in NVDA (Tools > Manage add-ons)."
							)
						elif attached and calls > 0 and not entries:
							report.info(
								f"DIAGNOSIS: listener fired {calls} times but all "
								"utterances had empty text after extraction. Check "
								"_extract_text() logic against NVDA's SpeechSequence "
								"content in this environment."
							)
					except Exception as debug_exc:  # noqa: BLE001
						report.warn(f"Could not fetch /debug/status: {debug_exc}")
					_nvda_log_hint(report)
					report.record("speech_log", False, "empty after 15s")
					all_tools_ok = False
				else:
					last = entries[-1]
					report.ok(f"Captured {count} utterance(s). Last: {last!r}")
					report.record("speech_log", True)

				# get_last_spoken now returns {"entry": Entry | None}
				last_result = await call("get_last_spoken")
				if not isinstance(last_result, dict) or "entry" not in last_result:
					raise RuntimeError(
						f"get_last_spoken should return {{'entry': ...}}, got {last_result!r}"
					)
				last_entry = last_result["entry"]
				report.info(f"get_last_spoken -> {last_entry!r}")
				report.record("get_last_spoken", True)
			except Exception as exc:  # noqa: BLE001
				report.fail(f"{exc}")
				if verbose:
					report.info(traceback.format_exc())
				report.record("speech_log", False, str(exc))
				all_tools_ok = False

			# --- 7. Focus info --------------------------------------
			report.banner(7, "get_focus_info")
			try:
				focus = await call("get_focus_info")
				if not focus:
					report.warn(
						"Empty focus info. NVDA may have no focus object "
						"(unusual) or the API call failed silently."
					)
					report.record("get_focus_info", False, "empty result")
					all_tools_ok = False
				else:
					report.ok(f"Focus: role={focus.get('role')!r} name={focus.get('name')!r}")
					report.record("get_focus_info", True)
			except Exception as exc:  # noqa: BLE001
				report.fail(f"{exc}")
				report.record("get_focus_info", False, str(exc))
				all_tools_ok = False

			# --- 8. Keyboard injection (opt-in) --------------------
			report.banner(8, "Keyboard injection (opt-in)")
			if not do_send_keys:
				report.info("Skipped. Re-run with --send-keys to enable.")
				report.record("keyboard", True, "skipped")
			else:
				try:
					report.info("Opening the Run dialog (Win+R) -> notepad -> Enter ...")
					await call("send_key", {"gesture": "windows+r"})
					await asyncio.sleep(0.8)
					await call("type_text", {"text": "notepad"})
					await call("send_key", {"gesture": "enter"})
					await asyncio.sleep(1.5)
					report.info("Typing 'hello from mcp' into whatever now has focus.")
					result = await call("type_text", {"text": "hello from mcp"})
					report.ok(f"type_text result: {result!r}")
					report.info(
						"Visually confirm that Notepad (or whatever window "
						"took focus) now contains 'hello from mcp'."
					)
					report.record("keyboard", True)
				except Exception as exc:  # noqa: BLE001
					report.fail(f"Keyboard injection failed: {exc}")
					if verbose:
						report.info(traceback.format_exc())
					report.record("keyboard", False, str(exc))
					return handshake_ok, False

	except Exception as exc:  # noqa: BLE001
		report.fail(f"MCP session failed to open: {exc}")
		if verbose:
			report.info(traceback.format_exc())
		report.info("Common causes:")
		report.info("  - The endpoint URL/path is wrong. Try --path /mcp/.")
		report.info("  - The installed 'mcp' SDK version does not match the server.")
		report.info("    Recommended: 'pip install \"mcp>=2.0,<3.0\"' on the client.")
		report.info("  - The server crashed on the initialize handshake; check NVDA log.")
		return handshake_ok, False

	return handshake_ok, all_tools_ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(
		description="Smoke test for the NVDA MCP Bridge add-on (uses the official mcp SDK client).",
	)
	p.add_argument("--host", default=DEFAULT_HOST, help=f"MCP host (default: {DEFAULT_HOST})")
	p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"MCP port (default: {DEFAULT_PORT})")
	p.add_argument("--path", default=DEFAULT_PATH, help=f"MCP URL path (default: {DEFAULT_PATH})")
	p.add_argument(
		"--send-keys",
		action="store_true",
		help="Actually inject keys (opens Notepad and types 'hello from mcp').",
	)
	p.add_argument("--verbose", action="store_true", help="Print tracebacks and raw payloads.")
	p.add_argument(
		"--report",
		default=None,
		help=f"Path to the report file (default: ./{REPORT_FILENAME}).",
	)
	return p.parse_args()


def main() -> int:
	args = parse_args()
	report_path = args.report or os.path.join(os.getcwd(), REPORT_FILENAME)
	report = Report(report_path)

	try:
		report.banner(1, "Environment")
		_dump_env(report)

		# Fail fast if the client SDK is missing.
		import_mcp_or_die(report)

		report.banner(2, "Endpoint reachability (stdlib TCP + /health probe)")
		if not probe_endpoint(args.host, args.port, args.path, report, args.verbose):
			report.record("reachability", False, "endpoint unreachable")
			report.summary()
			return 1
		report.record("reachability", True)

		url = f"http://{args.host}:{args.port}{args.path}"
		handshake_ok, tools_ok = asyncio.run(
			run_mcp_tests(url, report, args.verbose, args.send_keys)
		)

		all_ok = report.summary()
		if not handshake_ok:
			return 2
		if args.send_keys and not tools_ok:
			return 4
		if not tools_ok:
			return 3
		return 0 if all_ok else 3
	except KeyboardInterrupt:
		report.fail("Interrupted by user.")
		report.summary()
		return 20
	except Exception as exc:  # noqa: BLE001
		report.fail(f"Unexpected top-level error: {exc}")
		report.info(traceback.format_exc())
		report.summary()
		return 99
	finally:
		report.close()


if __name__ == "__main__":
	sys.exit(main())