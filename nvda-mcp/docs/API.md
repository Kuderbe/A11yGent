# NVDA MCP Bridge — API Reference

This document is the authoritative external reference for the
NVDA MCP Bridge add-on. The same content is also served **live**
by the running server itself via MCP `resources/read` on the URI
`nvda-mcp://docs/api`, so agent clients that speak the full MCP
surface (Claude Desktop, Cline, Anthropic's reference SDK) can
fetch it on demand without you having to paste it into a prompt.

- **Version:** v0.1.2 (Windows-verified 2026-07-30 on NVDA 2026.1.1;
  agent-guide v2 with Object Navigation, table cell navigation,
  Desktop-vs-Laptop layout, and `get_focus_info` fast-path for
  read-only edit controls, all distilled from the **NVDA Coach**
  Interactive Screen Reader Training add-on)
- **Transport:** MCP over Streamable HTTP, JSON-RPC 2.0
- **Endpoint:** `POST http://127.0.0.1:8765/mcp`
- **Wire spec:** [Model Context Protocol](https://modelcontextprotocol.io)

---

## 1. HTTP endpoints

| Method | Path            | Purpose |
|--------|-----------------|---------|
| GET    | `/health`       | Liveness probe → `{"status":"ok"}` |
| GET    | `/debug/status` | Diagnostic snapshot: uptime, listener state, NVDA extension-point ground truth, buffered speech count |
| GET    | `/mcp`          | Returns `405 Method Not Allowed` with a hint pointing to POST |
| POST   | `/mcp`          | JSON-RPC 2.0 MCP endpoint (see below) |
| OPTIONS| any             | CORS preflight response |

`GET /debug/status` example response:

```json
{
  "server": {
    "name": "nvda-mcp",
    "version": "0.1.0",
    "uptime_seconds": 42.7,
    "endpoint": "http://127.0.0.1:8765/mcp"
  },
  "speech_log": {
    "self_id": 140234456789,
    "listener_attached": true,
    "is_active_receiver": true,
    "pre_speech_call_count": 128,
    "buffered_entries": 87,
    "next_id": 129
  },
  "nvda_extension_points": {
    "active_speech_log_id": 140234456789,
    "pre_speech_available": true,
    "pre_speech_handler_count": 4,
    "pre_speech_our_handler_registered": true,
    "pre_speechQueued_available": true,
    "pre_speechQueued_handler_count": 3,
    "pre_speechQueued_our_handler_registered": true
  },
  "input_backends": ["keyboard"],
  "auth_enabled": false
}
```

---

## 2. MCP methods

All MCP interaction happens over `POST /mcp` with a JSON-RPC 2.0
envelope. The server advertises the following capabilities during
`initialize`:

```json
{
  "capabilities": {
    "tools":     {"listChanged": false},
    "prompts":   {"listChanged": false},
    "resources": {"listChanged": false, "subscribe": false}
  },
  "serverInfo": {"name": "nvda-mcp", "version": "0.1.0"}
}
```

### 2.1 `initialize`

Handshake. Send whatever `protocolVersion` your client supports;
the server echoes it back.

```json
// request
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":"2025-03-26",
  "clientInfo":{"name":"my-agent","version":"1.0"},
  "capabilities":{}}}

// response
{"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-03-26",
  "capabilities":{...},
  "serverInfo":{"name":"nvda-mcp","version":"0.1.0"}}}
```

### 2.2 `ping`

Empty-result keep-alive: `{"jsonrpc":"2.0","id":n,"method":"ping"}` → `{"result":{}}`.

### 2.3 `tools/list`

Enumerate all tools with their JSON-Schema input contract.

```json
// response.result
{
  "tools": [
    {
      "name": "get_speech_log",
      "description": "Return recent utterances spoken by NVDA ...",
      "inputSchema": {
        "type": "object",
        "properties": {
          "limit":    {"type": "integer", "default": 50},
          "since_id": {"type": "integer", "default": 0}
        },
        "additionalProperties": false
      }
    },
    ...
  ]
}
```

### 2.4 `tools/call`

Invoke a tool by name. Result is a `CallToolResult` with a JSON
text block plus `structuredContent`.

```json
// request
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
  "name":"send_key",
  "arguments":{"gesture":"NVDA+t"}}}

// response.result
{
  "content":[{"type":"text","text":"{\"ok\":true,\"gesture\":\"NVDA+t\"}"}],
  "structuredContent":{"ok":true,"gesture":"NVDA+t"},
  "isError":false
}
```

**Tool return contract.** Every tool's `structuredContent` is a JSON
**object** (not an array or primitive). This is required by the MCP
spec and validated strictly by the reference SDK's pydantic models.

### 2.5 `prompts/list`

Enumerate pre-canned prompt templates.

```json
// response.result
{
  "prompts": [
    {
      "name": "quick_nav_walkthrough",
      "title": "Quick-nav walkthrough of the focused app",
      "description": "Guides the agent through exploring ...",
      "arguments": []
    },
    ...
  ]
}
```

### 2.6 `prompts/get`

Fetch the full message body of one prompt.

```json
// request
{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{
  "name":"quick_nav_walkthrough"}}

// response.result
{
  "description":"Guides the agent through ...",
  "messages":[{"role":"user","content":{"type":"text","text":"You are ..."}}]
}
```

Agent clients like Claude Desktop and Cline surface these in the UI
as slash-commands the user can invoke; the retrieved message content
is injected into the LLM's context before the next turn.

### 2.7 `resources/list`

Enumerate read-only reference documents.

```json
// response.result
{
  "resources": [
    {"uri":"nvda-mcp://docs/api",       "name":"API reference",       ...},
    {"uri":"nvda-mcp://docs/gestures",  "name":"NVDA gesture syntax", ...},
    {"uri":"nvda-mcp://docs/workflows", "name":"Sample workflows",    ...}
  ]
}
```

### 2.8 `resources/read`

Fetch the full text of one resource by URI.

```json
// request
{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{
  "uri":"nvda-mcp://docs/gestures"}}

// response.result
{"contents":[{
  "uri":"nvda-mcp://docs/gestures",
  "mimeType":"text/markdown",
  "text":"# NVDA gesture reference\n\n..."}]}
```

### 2.9 `notifications/*`

The server accepts any `notifications/*` method (per JSON-RPC 2.0,
these are requests without an `id` field) and responds with HTTP
`204 No Content`. Nothing is done with them internally.

### 2.10 Error responses

Standard JSON-RPC error object:

```json
{"jsonrpc":"2.0","id":n,"error":{"code":-32601,"message":"Method not found: 'foo'"}}
```

| Code    | Meaning                                              |
|---------|------------------------------------------------------|
| -32700  | Parse error (invalid JSON body)                      |
| -32600  | Invalid request (not an object/array, missing fields)|
| -32601  | Method not found                                     |
| -32602  | Invalid params (missing/wrong-typed field)           |
| -32603  | Internal error (exception on the server)             |
| -32000  | Application-level tool error (also see `isError:true`)|

`tools/call` uses `isError: true` in the `CallToolResult` for
tool-level errors (invalid gesture, blocked auth, …) instead of
raising a JSON-RPC error. Transport/protocol errors still come back
as JSON-RPC errors.

---

## 3. Tools reference

All nine tools live at `POST /mcp` under `tools/call`. Common
`params` envelope:

```json
{"name":"<tool_name>","arguments":{...}}
```

### 3.1 `get_speech_log`

Poll the Speech-Viewer-equivalent utterance buffer.

| Field       | Type    | Default | Notes                                     |
|-------------|---------|---------|-------------------------------------------|
| `limit`     | integer | `50`    | 0 or negative means "no limit".            |
| `since_id`  | integer | `0`     | Return only entries with `id > since_id`. |

**Returns** `{entries: Entry[], count: int, since_id: int}` where
`Entry = {id: int, timestamp: float, text: str}`.

Timestamps are Unix seconds (float, sub-second precision). Ids are
monotonically increasing within one add-on session; they reset on
add-on reload.

Recommended polling pattern:

```
last = 0
loop:
    r = get_speech_log(since_id=last, limit=100)
    for e in r.entries:
        process(e)
        last = e.id
```

### 3.2 `get_last_spoken`

Convenience wrapper for "the most recent utterance".

**Returns** `{entry: Entry | null}`. `entry` is `null` iff the log
was just cleared or NVDA has not spoken yet.

### 3.3 `clear_speech_log`

Empty the ring buffer.

**Returns** `{ok: true}`. Does NOT reset `id` counters (subsequent
entries continue counting up).

Typical use: call before an action you want to observe, then poll
`get_speech_log` afterward to see just what NVDA said in response.

### 3.4 `send_key`

Simulate one key press using NVDA gesture syntax.

| Field     | Type   | Required |
|-----------|--------|----------|
| `gesture` | string | ✓        |

**Returns** `{ok: true, gesture: str}`.

Errors: invalid gesture strings raise a tool-level error
(`isError: true`) with a human-readable message.

Common examples:

- `"a"` — literal letter a.
- `"enter"` — Enter key.
- `"control+a"` — Ctrl-A (select all in most editors).
- `"NVDA+t"` — NVDA modifier + T (announce window title).
- `"NVDA+f7"` — open the element list dialog in browse mode.

See resource `nvda-mcp://docs/gestures` for the full grammar.

**Dispatch routing.** `send_key` (and by extension `send_keys` /
`type_text`) uses a two-tier dispatch strategy:

- If the parsed gesture is bound to an NVDA script (all `NVDA+*`
  commands and every browse-mode quick-nav letter like `h`, `d`, `k`,
  `1..6`, `NVDA+f7`, `NVDA+space`, ...), it is dispatched **directly**
  through `inputCore.manager.executeGesture()`. This bypasses
  `KeyboardInputGesture.send()`'s `ignoreInjection()` wrapper, which
  would otherwise cause NVDA's own low-level keyboard hook to drop
  the synthetic keystroke before it could reach the script layer.
- Pure OS/app keystrokes (`tab`, `control+l`, `enter`, `windows+d`,
  literal characters, ...) fall back to
  `KeyboardInputGesture.send()`, i.e. real `winUser.keybd_event`
  Windows messages.

The routing is automatic — callers use the same gesture string
either way. See resource `nvda-mcp://docs/agent-guide` §12 for the
internals.

### 3.5 `send_keys`

Chain of gestures with optional delay.

| Field       | Type       | Required | Default |
|-------------|------------|----------|---------|
| `gestures`  | string[]   | ✓        |         |
| `delay_ms`  | integer    |          | 0       |

**Returns** `{ok: true, sent: int}` where `sent` is the number of
gestures actually issued (may be less than `len(gestures)` if the
sequence was aborted mid-way).

Example:

```json
{"name":"send_keys","arguments":{
  "gestures":["tab","tab","enter"],
  "delay_ms":150}}
```

### 3.6 `type_text`

Type a literal string. Each character is decomposed into individual
gestures using NVDA's own layout awareness. Newlines are mapped to
`enter`, tabs to `tab`. Characters that cannot be produced on the
current keyboard layout are silently skipped.

| Field       | Type    | Required | Default |
|-------------|---------|----------|---------|
| `text`      | string  | ✓        |         |
| `delay_ms`  | integer |          | 0       |

**Returns** `{ok: true, sent: int, requested: int}` where
`sent ≤ requested` (drop count = unsupported characters).

### 3.7 `get_focus_info`

Snapshot of NVDA's current focus object. Runs synchronously on
NVDA's main thread.

**No arguments.**

**Returns:**

```json
{
  "name": "OK",
  "value": "",
  "description": "",
  "role": "BUTTON",
  "states": ["FOCUSABLE", "FOCUSED"],
  "windowClassName": "Button",
  "windowText": "OK",
  "appModule": "chrome"
}
```

Field notes:

- `name` is the accessible name — often the visible label, but may
  be an `aria-label`, `title`, or synthesized from surrounding text.
- `role` is the NVDA `controlTypes.Role` enum member name (e.g.
  `BUTTON`, `EDITABLETEXT`, `LINK`, `HEADING`, `LANDMARK`, …).
- `states` is a sorted list of NVDA `controlTypes.State` enum
  member names (e.g. `FOCUSED`, `SELECTED`, `EXPANDED`, `INVALID`).
- `appModule` is the name of NVDA's app-specific module handling
  the process, roughly the app's executable name (e.g. `chrome`,
  `firefox`, `winword`, `explorer`).
- If NVDA has no focus (very unusual), returns `{}`.
- If the NVDA API is unavailable (add-on run outside NVDA), returns
  `{"error": "NVDA API unavailable: ..."}`.

### 3.8 `get_braille_state`

Snapshot of the braille row NVDA is currently rendering. This is
the equivalent of the built-in Braille Viewer (Tools -> Braille
viewer), and it is a second, independent ground-truth signal
alongside `get_speech_log`: many controls, status markers, and
formatting indicators are conveyed in braille that never appear as
speech, and vice versa.

**No arguments.**

**Returns:**

```json
{
  "cells": [45, 62, 20, 0, 0, 0],
  "braille_unicode": "\u282d\u283e\u2814\u2800\u2800\u2800",
  "raw_text": "Button OK",
  "cell_count": 40,
  "timestamp": 1735300000.123,
  "display": {
    "name": "No braille",
    "size": 40
  }
}
```

Field notes:

- `cells` is one 8-bit dot pattern per braille cell. Bits 0..7 map
  to dots 1..8; value range is 0..255. Empty cell = 0.
- `braille_unicode` is the same information as `cells` rendered
  into Unicode Braille Patterns (block U+2800..U+28FF), one glyph
  per cell. This is what the Braille Viewer window shows.
- `raw_text` is the source string that produced those cells,
  before translation to the active braille table. Useful when the
  braille output uses contractions and you want the plain-text
  interpretation.
- `cell_count` is what NVDA is currently rendering to (may be
  smaller than `display.size` when `filter_displayDimensions` is
  active, e.g. via NVDA's Remote Access feature).
- `display.name` / `display.size` come from `braille.handler`. If
  no physical display is connected, `name` will typically be
  `"No braille"` and `size` may be 0.
- `timestamp` is `null` until NVDA has written braille at least
  once since this add-on session started. Data hooks into
  `braille.extensions.pre_writeCells`, which fires whenever NVDA
  updates its braille output, including when the Braille Viewer
  is the sole receiver. If `timestamp` never becomes non-null,
  either NVDA has not rendered braille yet (open the Braille
  Viewer or connect a display to force writes) or the extension
  point registration failed (check `GET /debug/status` under
  `nvda_extension_points.braille`).

### 3.9 `get_server_info`

Metadata about the running server.

**No arguments.**

**Returns:**

```json
{
  "name": "nvda-mcp",
  "version": "0.1.0",
  "host": "127.0.0.1",
  "port": 8765,
  "path": "/mcp",
  "auth_enabled": false,
  "input_backends": ["keyboard"]
}
```

Useful for capability discovery: an agent can call this first to
find out which input backends are wired up (future versions may
add `mouse`, `touch`, …).

---

## 4. Prompt templates

The server ships four pre-canned prompt templates for common
agent tasks. Fetch via `prompts/get` with the `name` parameter.

| Name                    | Purpose |
|-------------------------|---------|
| `nvda_agent_playbook`   | **Start here.** Compact operating rules for driving NVDA correctly: points at the full agent-guide resource, enforces the perception loop, quick-nav priority, mode-trap avoidance, and the "user skill vs. real barrier" distinction. |
| `quick_nav_walkthrough` | Guides an agent through exploring the focused app using screen-reader quick-nav semantics (h/k/f/b/d). |
| `accessibility_audit`   | Structured barrier report driven by speech-log evidence — walks tab order, quotes NVDA utterances as proof. |
| `capture_and_explain`   | Explain the current speech log entry-by-entry as a blind user would perceive it. |

Full text is embedded in `mcp_server.py` (`_PROMPT_*` constants)
and served live via `prompts/get`.

---

## 5. Resources

Read-only reference documents. Fetch via `resources/read` with the
`uri` parameter.

| URI                              | Content |
|----------------------------------|---------|
| `nvda-mcp://docs/agent-guide`    | **Start here.** Agent-specific digest of NVDA's user guide (v2026.1.1) plus the **NVDA Coach — Interactive Screen Reader Training** add-on (v1.5.4). v2 (2026-07-30) adds: the three-layer keyboard command model, the four cursor / two mode mental model, **Desktop vs. Laptop keyboard layout** and every command whose binding differs, **Object Navigation** (full command set + recipe for reaching Tab-unreachable custom widgets), **`Ctrl+Alt+Arrow` table cell navigation**, the `get_focus_info` fast-path for read-only multi-line edit controls, `NVDA+F7` Elements List filter shortcuts, and the "inexperienced user vs. real barrier" decision rule extended with two more affordances (Elements List and Object Navigation) that must be tried before flagging a barrier. |
| `nvda-mcp://docs/api`            | Condensed version of this document, embedded in the add-on itself. |
| `nvda-mcp://docs/gestures`       | Complete NVDA gesture-string reference (modifiers, browse-mode letters, global gestures). |
| `nvda-mcp://docs/workflows`      | Four concrete example workflows an agent can follow. |

---

## 6. NVDA gesture syntax (summary)

See resource `nvda-mcp://docs/gestures` for the full document.
Short version:

- **Modifiers:** `control`/`ctrl`, `shift`, `alt`, `windows`/`win`, `NVDA`.
- Combine with `+`: `"control+shift+end"`, `"NVDA+f7"`.
- **Named keys:** `enter`, `escape`, `tab`, `space`, `upArrow`,
  `downArrow`, `leftArrow`, `rightArrow`, `home`, `end`, `pageUp`,
  `pageDown`, `backspace`, `delete`, `insert`, `f1` .. `f24`.
- **Literal characters:** `a`, `1`, etc. (single-character strings).
- **Literal plus:** `plus` (the string `"+"` alone would be parsed
  as a malformed combo).
- **Browse-mode quick-nav** (single letters when focus is inside a
  browser page / rich document): `h`/`shift+h` = next/prev heading,
  `k` = next link, `f` = next form field, `b` = next button,
  `d` = next landmark, `t` = next table, `l` = next list,
  `NVDA+f7` = element list dialog.

---

## 7. Threading model

- The MCP server runs on a dedicated daemon thread hosting a
  `http.server.ThreadingHTTPServer`. Each incoming HTTP request is
  handled on its own worker thread.
- Every tool that touches NVDA API state (`get_focus_info`,
  `send_key`, `send_keys`, `type_text`) is marshalled back to
  NVDA's wx main thread via `main_thread.run_on_main_thread`,
  which blocks the calling worker thread until NVDA finishes.
- The speech log is a bounded `collections.deque` protected by a
  `threading.Lock`. NVDA's main thread writes, worker threads
  read; the lock guarantees consistent snapshots.

---

## 8. Authentication

v0.1.0 has authentication **plumbed but disabled**:

- `config.ENABLE_AUTH = False` (default).
- Every tool call goes through `ctx.auth.authenticate(...)` — this
  is a no-op via the `AllowAllAuth` provider by default.
- A reference `BearerTokenAuth` provider is present in `auth.py`.

To enable auth in a future version:

1. Set `config.ENABLE_AUTH = True` and `config.AUTH_TOKEN = "..."`.
2. Point `auth.build_default_auth()` at `BearerTokenAuth(token=...)`.
3. Clients must send `Authorization: Bearer <token>` on every
   `POST /mcp` request.

Server binding stays localhost-only (`127.0.0.1`) regardless.

---

## 9. Client usage examples

### 9.1 Official `mcp` SDK v2 (Python)

```python
import asyncio
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:8765/mcp") as c:
        # Tools
        tools = await c.list_tools()
        print(f"{len(tools.tools)} tools available")
        last = await c.call_tool("get_last_spoken", {})
        print(last.structured_content)

        # Prompts
        prompts = await c.list_prompts()
        for p in prompts.prompts:
            print(p.name, "-", p.description[:60])
        walkthrough = await c.get_prompt("quick_nav_walkthrough", {})
        # walkthrough.messages[0].content.text is the guiding instructions

        # Resources
        resources = await c.list_resources()
        api_doc = await c.read_resource("nvda-mcp://docs/api")
        # api_doc.contents[0].text is the full API markdown

asyncio.run(main())
```

### 9.2 Stdlib-only (`urllib`)

```python
import json, urllib.request

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

print(rpc("initialize", {
    "protocolVersion": "2025-03-26",
    "clientInfo": {"name": "demo", "version": "0"},
    "capabilities": {}}))
print(rpc("tools/list", req_id=2))
print(rpc("prompts/list", req_id=3))
print(rpc("resources/list", req_id=4))
print(rpc("resources/read",
          {"uri": "nvda-mcp://docs/api"}, req_id=5))
```

### 9.3 curl

```bash
# Health
curl -s http://127.0.0.1:8765/health

# Debug status
curl -s http://127.0.0.1:8765/debug/status | jq .

# List tools
curl -s -X POST http://127.0.0.1:8765/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .

# Send NVDA+t (announce window title)
curl -s -X POST http://127.0.0.1:8765/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
          "params":{"name":"send_key","arguments":{"gesture":"NVDA+t"}}}' | jq .

# Fetch the API reference resource
curl -s -X POST http://127.0.0.1:8765/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":3,"method":"resources/read",
          "params":{"uri":"nvda-mcp://docs/api"}}' | jq -r '.result.contents[0].text'
```

### 9.4 Claude Desktop / Cline

Add a Streamable-HTTP MCP server pointing at
`http://127.0.0.1:8765/mcp`. Both clients auto-discover the tools,
the prompt templates (as slash-commands), and the reference
resources (as attachable documents).

---

## 10. Diagnostics & troubleshooting

### 10.1 Debug endpoint

Any time speech capture behaves unexpectedly, hit `GET /debug/status`.

- `speech_log.listener_attached: false` → `SpeechLog.start()` was
  never called, or raised. Check the NVDA log for a traceback from
  `nvda-mcp`.
- `speech_log.pre_speech_call_count: 0` after NVDA has visibly
  spoken → our handler is registered but not being called; usually
  a multi-instance issue (see `_active_speech_log` in
  `speech_log.py`) or NVDA started with `--disable-addons`.
- `nvda_extension_points.pre_speech_our_handler_registered: false`
  → we lost our slot in NVDA's `_handlers` OrderedDict. Toggle the
  MCP server off/on via the Input Gestures dialog under "MCP Bridge"
  category, or restart NVDA.

### 10.2 NVDA log

`%APPDATA%\nvda\nvda.log`. Look for lines starting with
`external:globalPlugins.nvdaMcp`. Expected startup sequence:

```
external:globalPlugins.nvdaMcp: nvda-mcp: module imported (config: ...)
external:globalPlugins.nvdaMcp: nvda-mcp: GlobalPlugin.__init__ start (init_counter=1)
external:globalPlugins.nvdaMcp.speech_log: nvda-mcp: SpeechLog attached ...
external:globalPlugins.nvdaMcp.mcp_server: nvda-mcp: HTTP MCP server listening at ...
external:globalPlugins.nvdaMcp: nvda-mcp: global plugin initialised ...
```

If the very first log line shows
`Provided arguments: ['--disable-addons', ...]`, NVDA won't load
any add-on and none of the above will appear.

### 10.3 Smoke test

`tests/smoke_test.py` on the Windows host drives the server with
the official `mcp` v2 SDK client through all 9 tools. Exit codes:
`0` OK, `1` unreachable, `2` handshake failed, `3` tool call
failed, `4` keyboard injection failed, `10` SDK missing,
`20` Ctrl+C, `99` other. Full report is written to
`smoke_test_report.txt`.

---

## 11. Versioning & compatibility

- **Add-on version:** v0.1.0 (see `manifest.ini`).
- **MCP protocol version advertised:** `2025-03-26`. Clients may
  request any version; we echo it back.
- **NVDA API compatibility:** `minimumNVDAVersion = 2024.1`,
  `lastTestedNVDAVersion = 2026.1`.
- **Tool return shapes** follow semantic versioning starting from
  v0.1.0. Adding fields to existing tool return objects is a minor
  bump; renaming or removing a field is a major bump.
- **Prompt names and resource URIs** are treated as stable API
  surface; they should not be renamed without a version bump.

---

## 12. Roadmap (post-v0.1.0)

- v0.2 — NVDA Settings panel for host/port/auth configuration;
  mouse input backend (`mouse_move`, `mouse_click`).
- v0.3 — Bearer-token auth activated by default; token file
  discovery under `%APPDATA%\nvda\`.
- Later — Braille-display observation backend; agent-side helpers
  for common workflows built on top of the tools.

## License

GNU General Public License v2 or later, matching NVDA itself.