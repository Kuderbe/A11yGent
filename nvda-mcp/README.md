# NVDA MCP Bridge

An NVDA add-on that exposes two capabilities of the NVDA screen reader over a
local [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server:

1. **Read the Speech Viewer** – every string NVDA is about to speak is
   captured and made available to MCP clients.
2. **Simulate keyboard input** – MCP clients can send arbitrary key
   gestures (`control+a`, `downArrow`, `NVDA+f`, …) or type text into
   whichever application currently has focus.

This lets AI agents (Claude Desktop, Cline, custom LangChain scripts, …)
*observe what a blind user hears* and *drive the same keystrokes a user
would*, which is the foundation for accessibility-aware agent evaluation
in the ongoing thesis work.

> **Status:** v0.1.0 – research prototype, **Windows-verified 2026-07-30**
> on NVDA 2026.1.1 (Windows 11 25H2 ARM64 host, AMD64 emulation). All 8
> smoke-test phases green when driven by the official Anthropic `mcp` v2
> Python SDK client. Keyboard input only; mouse and touch are planned.
> No authentication yet — the server binds to the host's primary IPv4
> so it is reachable from other machines on the same LAN (see
> "Networking" below). Use only in trusted private networks.
>
> **Zero third-party dependencies at runtime.** The MCP server is
> implemented against the Python standard library only (no `mcp` SDK,
> no `pydantic`, no `starlette`, no `uvicorn`). Total install footprint
> is ~50 KB.

---

## Repository layout

```
A11yGent/nvda-mcp/
├── manifest.ini                         # add-on metadata (top-level copy)
├── README.md                            # this file
├── .gitattributes                       # forces CRLF on *.bat
├── .gitignore
├── build.bat                            # produce nvdaMcp-<version>.nvda-addon
└── addon/                               # → root of the .nvda-addon zip
    ├── manifest.ini
    └── globalPlugins/
        ├── __init__.py
        └── nvdaMcp/
            ├── __init__.py              # GlobalPlugin: lifecycle + scripts
            ├── config.py                # host/port/log-size/auth constants
            ├── auth.py                  # AuthProvider ABC + AllowAllAuth
            ├── main_thread.py           # wx.CallAfter-based marshalling helper
            ├── speech_log.py            # pre_speech listener + ring buffer
            ├── input_bridge.py          # InputBackend ABC + KeyboardBackend
            └── mcp_server.py            # stdlib-only JSON-RPC 2.0 MCP server
```

## Runtime architecture

```
                                 ┌──────────────────────────────────────┐
                                 │              NVDA process            │
                                 │                                      │
                                 │   main (wx) thread                   │
                                 │   ┌───────────────────────────────┐  │
   speech.extensions.pre_speech ─┼─►│ SpeechLog._on_pre_speech       │  │
                                 │  └───────────────────────────────┘  │
                                 │              ▲                       │
                                 │              │ ring buffer (lock)    │
                                 │              │                       │
                                 │   nvda-mcp-server daemon thread      │
                                 │  ┌───────────────────────────────┐   │
   MCP client ── HTTP POST ──────┼─►│ ThreadingHTTPServer (stdlib)  │   │
   (Claude, Cline, curl, …)      │  │  └─ Dispatcher                │   │
                                 │  │      ├─ initialize            │   │
                                 │  │      ├─ tools/list            │   │
                                 │  │      └─ tools/call ────────┐  │   │
                                 │  │                            │  │   │
                                 │  │  Tools:                    │  │   │
                                 │  │    get_speech_log          │  │   │
                                 │  │    send_key / type_text ──┐│  │   │
                                 │  │    get_focus_info ────────┼┼──┼──►│ run_on_main_thread ──► NVDA API
                                 │  └───────────────────────────┼┼──┘   │
                                 └──────────────────────────────┼┼──────┘
```

Key points:

- The **MCP server runs in a background daemon thread** hosting a
  `http.server.ThreadingHTTPServer`. NVDA's UI thread is never blocked
  by HTTP I/O; each incoming request is handled on its own worker
  thread.
- Every tool that touches NVDA state (focus, keyboard injection) is
  marshalled back to NVDA's wx main thread via `run_on_main_thread` and
  waits synchronously for the result.
- The speech log is a bounded `collections.deque` protected by a
  `threading.Lock`. Writers (NVDA main thread) and readers (server
  worker threads) never see torn state.

## Wire protocol

Standard **MCP over Streamable HTTP**, JSON-RPC 2.0 payloads. One
endpoint: `POST http://127.0.0.1:8765/mcp`. Supported methods:

| Method              | Purpose                                              |
|---------------------|------------------------------------------------------|
| `initialize`        | Handshake; echoes the client's protocolVersion.      |
| `ping`              | Empty-result keep-alive.                             |
| `tools/list`        | Enumerate all tools with JSON schemas.               |
| `tools/call`        | Invoke a tool by name; returns wrapped result.       |
| `prompts/list`      | Enumerate pre-canned prompt templates.               |
| `prompts/get`       | Fetch the full message body of one prompt.           |
| `resources/list`    | Enumerate read-only reference documents.             |
| `resources/read`    | Fetch the content of one resource by URI.            |
| `notifications/*`   | Accepted, no response (per JSON-RPC 2.0).            |

Anything else returns `{"error": {"code": -32601, "message": "..."}}`.

The server advertises **tools + prompts + resources** as MCP
capabilities during `initialize`, so agent clients (Claude Desktop,
Cline, the reference SDK) auto-discover the entire API surface —
including instruction templates and reference documentation —
without any out-of-band configuration.

There is also `GET /health` (liveness probe → `{"status":"ok"}`) and
`GET /debug/status` (diagnostic snapshot: uptime, listener state,
NVDA extension-point ground truth) for monitoring and debugging.

**Full API reference:** [`docs/API.md`](docs/API.md). The same
document is served live by the running server at
`resources/read` with URI `nvda-mcp://docs/api`.

## Prompt templates & reference resources

Alongside the tools, the server exposes four **prompt templates**
that agents can inject into their own context and four **reference
resources** they can attach as documents.

**Prompts** (via `prompts/list` + `prompts/get`):

| Name                    | Purpose |
|-------------------------|---------|
| `nvda_agent_playbook`   | **Start here.** Compact operating rules for driving NVDA correctly (perception loop, quick-nav priority, mode-trap escape, "user skill vs. real barrier"). Points at the full agent guide resource below. |
| `quick_nav_walkthrough` | Step-by-step guidance for exploring the focused app with screen-reader quick-nav semantics (h/k/f/b/d) instead of raw arrows. |
| `accessibility_audit`   | Structured barrier report driven by speech-log evidence; walks tab order and quotes NVDA utterances. |
| `capture_and_explain`   | Explain the current speech log utterance-by-utterance as a blind user would perceive it. |

**Resources** (via `resources/list` + `resources/read`):

| URI                              | Content |
|----------------------------------|---------|
| `nvda-mcp://docs/agent-guide`    | **Start here.** Agent-specific digest of NVDA's user guide (v2026.1.1) plus the **NVDA Coach** Interactive Screen Reader Training add-on. v2 (2026-07-30) covers: the three-layer keyboard command model, the four cursor / two mode mental model, **Desktop vs. Laptop keyboard layout** (every command whose binding differs), **Object Navigation** (full command set + recipe for reaching Tab-unreachable custom widgets), **`Ctrl+Alt+Arrow` table cell navigation**, the `get_focus_info` fast-path for read-only multi-line edit controls, `NVDA+F7` Elements List filter shortcuts, and the "inexperienced user vs. real barrier" decision rule extended with Elements List + Object Navigation as required affordances to try before flagging a barrier. |
| `nvda-mcp://docs/api`            | Condensed API reference — same content as `docs/API.md`. |
| `nvda-mcp://docs/gestures`       | Full NVDA gesture-string reference (modifiers, browse-mode letters, global gestures). |
| `nvda-mcp://docs/workflows`      | Four concrete example workflows (read focus, walk a form, explore headings, detect barriers). |

In Claude Desktop and Cline these surface automatically as
slash-commands and attachable documents respectively — no
configuration required. Agents driving this bridge for the first
time should fetch `nvda-mcp://docs/agent-guide` **before** issuing
any input, and inject the `nvda_agent_playbook` prompt into their
system context.

## Tools exposed (v0.1.0)

| Tool               | Signature                                                          | Purpose |
|--------------------|--------------------------------------------------------------------|---------|
| `get_speech_log`   | `(limit:int=50, since_id:int=0) → {entries:Entry[], count, since_id}` | Poll the Speech-Viewer-equivalent text log. |
| `get_last_spoken`  | `() → {entry: Entry \| null}`                                      | Most recent utterance only; `entry` is `null` if the log is empty. |
| `clear_speech_log` | `() → {ok}`                                                        | Reset the buffer (e.g. before a new task). |
| `send_key`         | `(gesture:str) → {ok, gesture}`                                    | Simulate one key/chord (`"control+a"`, `"downArrow"`, …). |
| `send_keys`        | `(gestures:list[str], delay_ms:int=0) → {ok, sent}`                | Sequence of key gestures. |
| `type_text`        | `(text:str, delay_ms:int=0) → {ok, sent, requested}`               | Type an arbitrary string. |
| `get_focus_info`   | `() → {role, name, value, states, …}`                              | Snapshot of the currently focused UI object. |
| `get_braille_state`| `() → {cells:int[], braille_unicode, raw_text, cell_count, timestamp, display:{name,size}}` | Snapshot of the row NVDA is currently rendering to braille (equivalent of the built-in Braille Viewer). |
| `get_server_info`  | `() → {name, version, host, port, path, …}`                        | Server metadata for capability discovery. |

An `Entry` is `{id:int, timestamp:float, text:str}`.

> **Tool return shape:** every tool returns a JSON **object** (not a bare
> array or primitive). This is because the MCP spec requires
> `structuredContent` to be an object, and the reference `mcp` SDK
> client validates strictly against that. Collection-returning tools
> (`get_speech_log`) therefore wrap their list in an `entries` field.

Gesture strings follow NVDA's own naming (see `nvda/source/keyboardHandler.py`
and `nvda/source/vkCodes.py`): `"a"`, `"enter"`, `"escape"`, `"tab"`,
`"space"`, `"upArrow"`, `"downArrow"`, `"leftArrow"`, `"rightArrow"`,
`"home"`, `"end"`, `"pageUp"`, `"pageDown"`, `"backspace"`, `"delete"`,
`"insert"`, `"f1"`…`"f24"`, `"control+shift+end"`, `"NVDA+f"`, `"windows+d"`,
`"plus"` (literal `+`), etc.

> **How keystrokes are routed.** `send_key` / `send_keys` / `type_text`
> use a **two-tier dispatch strategy**. If the parsed gesture is bound
> to an NVDA script (all `NVDA+*` commands, `NVDA+f7`, `NVDA+space`, and
> every browse-mode quick-nav letter like `h` / `d` / `k` / `1..6`),
> the bridge dispatches it **directly** through
> `inputCore.manager.executeGesture()`. That is required because
> `KeyboardInputGesture.send()` wraps its OS-level `winUser.keybd_event`
> calls in `ignoreInjection()`, which makes NVDA's own low-level
> keyboard hook drop its own synthetic keystrokes — so `NVDA+n`,
> `NVDA+space`, `h`, `d`, etc. would silently no-op if we relied on OS
> injection alone. Pure OS keystrokes (`tab`, `control+l`, `enter`,
> literal characters, ...) fall back to `KeyboardInputGesture.send()`
> as before. The routing is automatic — callers use the same gesture
> string either way; see resource `nvda-mcp://docs/agent-guide` §12
> for the details.

## Building the add-on

NVDA is Windows-only, so the build script is Windows-only. There are
no runtime dependencies to install — nothing is vendored, no
`pip install` step exists.

```bat
:: Zip everything under addon\ into a .nvda-addon.
build.bat
```

Output: `nvdaMcp-0.1.0.nvda-addon` in the repo root (~50 KB).

## Installing in NVDA

1. Open NVDA → **Menu → Tools → Manage add-ons → Install…**
2. Select `nvdaMcp-0.1.0.nvda-addon`.
3. Restart NVDA when prompted.

The server auto-starts on `http://<primary-ipv4>:8765/mcp` (Streamable
HTTP transport). The actual bind address is auto-detected — see below.

## Networking: bind address, remote clients, Cline

The server binds to whatever the OS reports as the primary IPv4 of
the current host — the address that `ipconfig` on Windows (or
`ifconfig` on POSIX) shows on the active network adapter. That
means:

- On a **VM with a private network** (e.g. UTM/QEMU on macOS with
  the default `192.168.64.0/24` subnet), the server is reachable
  from the host as `http://192.168.64.X:8765/mcp` without any
  manual configuration.
- On a **workstation with no network**, or where the hostname
  resolves only to `127.0.0.1`, the code falls through to a UDP
  outbound-route probe (no packets are actually sent) to find the
  active interface. Ultimate fallback is `127.0.0.1`.

The actual bind address is logged at startup and reported by both
`GET /debug/status` and the `get_server_info` MCP tool:

```
external:globalPlugins.nvdaMcp.mcp_server:
  nvda-mcp: HTTP MCP server listening at http://192.168.64.5:8765/mcp
  (diagnostics: http://192.168.64.5:8765/debug/status)
```

> **Security note:** authentication is disabled in v0.1.0. Binding
> to a non-loopback address exposes NVDA control to every host on
> that LAN. Only do this in a trusted private network (e.g. a dev
> VM). See §Extending → "Add authentication" below to switch on the
> `BearerTokenAuth` provider before exposing the server more widely.

### Overriding the bind address

If you want localhost-only for extra safety, edit
`addon/globalPlugins/nvdaMcp/config.py`:

```python
MCP_HOST: str = "127.0.0.1"   # replace the _detect_primary_ipv4() call
```

Rebuild + reinstall the add-on afterward.

### Firewall rule (Windows)

Windows may prompt on first bind. If it doesn't, or you accepted
"Cancel" by accident, add the rule manually in an elevated
PowerShell:

```powershell
New-NetFirewallRule -DisplayName "NVDA MCP Bridge" `
                    -Direction Inbound -Protocol TCP `
                    -LocalPort 8765 -Action Allow -Profile Any
```

### Verify from a remote host

```bash
# From the host machine:
curl -s http://192.168.64.X:8765/health
# → {"status":"ok"}

curl -s http://192.168.64.X:8765/debug/status | jq .
```

### Adding the server to Cline

In VS Code open the command palette (`Cmd`/`Ctrl` + `Shift` + `P`)
and run **"Cline: Open MCP Settings"**. Add an entry under
`mcpServers`:

```json
{
  "mcpServers": {
    "nvda-mcp": {
      "type": "streamableHttp",
      "url": "http://192.168.64.X:8765/mcp",
      "disabled": false,
      "autoApprove": [
        "get_speech_log",
        "get_last_spoken",
        "get_focus_info",
        "get_braille_state",
        "get_server_info"
      ]
    }
  }
}
```

Replace `192.168.64.X` with the IP printed in NVDA's log (or
returned by `get_server_info`). The listed `autoApprove` names are
the read-only tools that never move focus or type; leaving
`send_key`, `send_keys`, `type_text`, and `clear_speech_log` out of
`autoApprove` means Cline will ask before every keystroke, which is
the desired behaviour for a screen-reader-driving agent.

Once saved, Cline discovers the server automatically. The MCP-server
panel in Cline should list `nvda-mcp` as "connected" and show:

- **Tools** (9): `get_speech_log`, `get_last_spoken`,
  `clear_speech_log`, `send_key`, `send_keys`, `type_text`,
  `get_focus_info`, `get_braille_state`, `get_server_info`.
- **Prompts** (4): `nvda_agent_playbook`, `quick_nav_walkthrough`,
  `accessibility_audit`, `capture_and_explain` — surfaced as
  slash-commands.
- **Resources** (4): `nvda-mcp://docs/agent-guide`,
  `nvda-mcp://docs/api`, `.../gestures`, `.../workflows` —
  attachable reference documents.

### Adding the server to Claude Desktop

Claude Desktop's `claude_desktop_config.json` uses the same shape:

```json
{
  "mcpServers": {
    "nvda-mcp": {
      "url": "http://192.168.64.X:8765/mcp"
    }
  }
}
```

(Config file location: on macOS
`~/Library/Application Support/Claude/claude_desktop_config.json`.)

## Talking to the server

### From the command line

Health check:

```bash
curl -s http://127.0.0.1:8765/health
# → {"status":"ok"}
```

List tools:

```bash
curl -s -X POST http://127.0.0.1:8765/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Call a tool:

```bash
curl -s -X POST http://127.0.0.1:8765/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
          "params":{"name":"get_last_spoken","arguments":{}}}'
```

### From Python (stdlib only)

```python
import json
import urllib.request

URL = "http://127.0.0.1:8765/mcp"

def rpc(method, params=None, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        URL, data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

print(rpc("initialize", {"protocolVersion": "2025-03-26",
                          "clientInfo": {"name": "demo", "version": "0"},
                          "capabilities": {}}))
print(rpc("tools/list", req_id=2))
print(rpc("tools/call",
          {"name": "get_last_spoken", "arguments": {}}, req_id=3))
print(rpc("tools/call",
          {"name": "send_key", "arguments": {"gesture": "NVDA+t"}},
          req_id=4))
```

### From Claude Desktop / Cline / other MCP clients

Add an MCP server entry pointing at `http://127.0.0.1:8765/mcp`. Any
client that speaks the standard MCP Streamable-HTTP transport will
work; the server implements enough of the spec (`initialize`,
`tools/list`, `tools/call`, `notifications/*`, `ping`) for practical
tool-calling flows.

## Smoke test

`tests/smoke_test.py` exercises every v1 tool against a running
add-on. It **uses the official Anthropic `mcp` Python SDK as its
client** — deliberately, so that a successful run proves the
server is spec-compliant enough for the reference client (and by
extension Claude Desktop, Cline, and other MCP clients) to drive
it. If we hand-rolled the test client, we'd only be checking our
own understanding of the protocol.

The `mcp` SDK is a *client-side* dependency: install it in whatever
Python you run the smoke test with. It does **not** live inside
the NVDA add-on itself (which remains stdlib-only).

Run it on the Windows box that hosts NVDA:

```bat
python -m pip install "mcp>=2.0,<3.0"            :: one-time client-side install
python tests\smoke_test.py                       :: safe: no key injection
python tests\smoke_test.py --send-keys           :: opens Notepad and types
python tests\smoke_test.py --verbose --port 9000 :: for debugging
```

What it checks, in order:

1. Python / platform info.
2. Raw TCP + HTTP reachability of `http://127.0.0.1:8765/mcp`, with a
   bespoke diagnosis for each failure mode (connection refused, timeout,
   non-HTTP service, etc.), plus a pointer to `%APPDATA%\nvda\nvda.log`.
3. MCP `initialize` handshake — prints the server-advertised name/version.
4. `tools/list` — verifies all 9 v1 tools are present.
5. `get_server_info` round-trip.
6. Speech log: `clear_speech_log` → 3-second window to make NVDA speak →
   `get_speech_log` / `get_last_spoken`. Warns if the log is empty.
7. `get_focus_info` snapshot.
8. **Opt-in** (`--send-keys`): opens Notepad via `Win+R` and types
   `hello from mcp`.
9. Summary table + a full log written to `smoke_test_report.txt`.

Exit codes: `0` success, `1` unreachable, `2` handshake failed, `3` tool
call failed, `4` keyboard injection failed, `10` `mcp` SDK missing on the
client side, `20` Ctrl+C, `99` unexpected error.

## Extending

The plugin was designed for easy extension.

- **Add a new input backend** (mouse, scroll, touch):

  1. Subclass `input_bridge.BaseInputBackend`.
  2. `registry.register(MyBackend())` in `build_default_registry`.
  3. Add new tool entries in `mcp_server._build_tools` — one
     `reg.register(ToolDef(name=..., handler=..., input_schema=...))`
     call per new tool.

- **Add authentication:**

  1. Implement an `auth.AuthProvider` subclass (a reference
     `BearerTokenAuth` is already in `auth.py`).
  2. Flip `config.ENABLE_AUTH = True` and set `config.AUTH_TOKEN`.
  3. The tool layer already calls `ctx.auth.authenticate(...)` before
     every operation.

- **Add a settings panel:** wire `config` constants to
  `gui.settingsDialogs.SettingsPanel` – no other module needs changes.

## Why hand-rolled instead of the official `mcp` SDK?

An earlier version of this add-on vendored the official `mcp` Python
SDK v2 under `_vendor/`. That fought a dependency-hell war on
multiple fronts:

- NVDA's embedded CPython 3.13 is py2exe-frozen and omits stdlib
  modules that some transitive deps expect (`multiprocessing`,
  `secrets`, `zoneinfo`).
- NVDA already ships compiled dependencies (`cryptography 48.0.1`,
  `rpyc 6.0.2`) at core start-up. Any vendored copy loses the
  `sys.modules` race and silently mismatches versions.
- Cross-compiling wheels for NVDA's Python 3.13 AMD64 (even on
  ARM64 Windows hosts, where NVDA runs under emulation) is a
  brittle pinning exercise.

The MCP Streamable-HTTP transport is small enough that a stdlib-only
JSON-RPC 2.0 server (~500 LOC in `mcp_server.py`) covers everything
we need for practical MCP clients. That is the current
implementation.

## Files worth reading first

- `addon/globalPlugins/nvdaMcp/__init__.py` – overall wiring.
- `addon/globalPlugins/nvdaMcp/mcp_server.py` – JSON-RPC dispatcher,
  tool registry, HTTP handler.
- `addon/globalPlugins/nvdaMcp/speech_log.py` – how the Speech Viewer
  content is captured.
- `addon/globalPlugins/nvdaMcp/braille_state.py` – how the current
  braille output is captured (Braille Viewer equivalent).
- `addon/globalPlugins/nvdaMcp/input_bridge.py` – how keys are injected.

## License

GNU General Public License v2 or later, matching NVDA itself.