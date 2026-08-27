# A part of the NVDA MCP Bridge add-on.
# Licensed under the GNU General Public License v2 or later.
"""
Hand-rolled MCP server for the NVDA MCP Bridge.

Why hand-rolled?
----------------
An earlier version of this file used the official ``mcp`` Python SDK,
vendored under ``_vendor/``. That approach fought a dependency-hell
war on multiple fronts:

* NVDA's embedded CPython 3.13 is py2exe-frozen and is missing a
  handful of stdlib modules (``multiprocessing``, ``secrets``, …).
* NVDA already ships some compiled deps (e.g. ``cryptography 48.0.1``),
  which collide with any vendored copy the SDK's transitive deps pull
  in.
* pinning wheels for the right ABI/platform tag and cross-compiling
  them from a developer machine is a maintenance minefield.

So we replaced the SDK with a small, stdlib-only implementation of
just enough of the MCP Streamable HTTP transport to satisfy standard
MCP clients (Anthropic's own Python client, Claude Desktop, Cline, …)
calling our ~8 tools.

Wire format
-----------
The server serves one endpoint (``POST {MCP_PATH}``) that accepts
JSON-RPC 2.0 requests and returns JSON-RPC 2.0 responses. We
recognise:

  * ``initialize``         – handshake, advertises server info + capabilities
  * ``ping``               – trivial keep-alive
  * ``tools/list``         – returns registered tools and JSON schemas
  * ``tools/call``         – invokes a tool by name, returns wrapped result
  * ``prompts/list``       – returns pre-canned prompt templates
  * ``prompts/get``        – returns the full message body of one prompt
  * ``resources/list``     – returns read-only reference documents
  * ``resources/read``     – returns the content of one resource by URI
  * ``notifications/*``    – accepted, no-op

Everything else returns an "unknown method" JSON-RPC error.

We also expose:
  * ``GET  /health``       – returns ``{"status":"ok"}`` for external checks
  * ``GET  /debug/status`` – NVDA-side ground truth for on-device debugging
  * ``GET  {MCP_PATH}``    – returns 405, but with an informative body

**Full MCP capabilities.** We advertise ``tools``, ``prompts``, and
``resources`` in ``initialize`` so that agent clients like Claude
Desktop or Cline auto-discover the entire API surface (tools + prompt
templates + reference documentation) without any out-of-band
configuration.

This is deliberately *not* a full spec implementation. We do not
implement SSE, elicitation, session cookies, or the notification
back-channel. All of our tools are synchronous request/response,
so a plain JSON POST is sufficient.
"""

from __future__ import annotations

import inspect
import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

from . import config
from .auth import AuthProvider, AuthError, build_default_auth
from .input_bridge import (
	InputError,
	InputRegistry,
	KeyboardBackend,
	build_default_registry,
)
from .main_thread import run_on_main_thread
from .speech_log import SpeechLog, SpeechEntry


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Server context object
# ---------------------------------------------------------------------------

class ServerContext:
	"""Shared state handed to every tool implementation."""

	def __init__(
		self,
		speech_log: SpeechLog,
		inputs: InputRegistry,
		auth: AuthProvider,
	) -> None:
		self.speech_log = speech_log
		self.inputs = inputs
		self.auth = auth

	@property
	def keyboard(self) -> KeyboardBackend:
		be = self.inputs.get("keyboard")
		if not isinstance(be, KeyboardBackend):
			raise RuntimeError("Keyboard backend not registered")
		return be


# ---------------------------------------------------------------------------
# JSON-RPC error codes
# ---------------------------------------------------------------------------

JSONRPC_PARSE_ERROR      = -32700
JSONRPC_INVALID_REQUEST  = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS   = -32602
JSONRPC_INTERNAL_ERROR   = -32603

# Application-level codes we return as error responses inside tools/call.
MCP_TOOL_ERROR = -32000


# ---------------------------------------------------------------------------
# Prompts and Resources content
# ---------------------------------------------------------------------------
#
# MCP has three peer surfaces: tools (things the agent can DO), prompts
# (pre-canned instructions the agent can inject into its own context),
# and resources (read-only documents the agent can fetch). We expose all
# three so that a compliant MCP client (Claude Desktop, Cline, the
# reference SDK, ...) discovers the full API surface without any
# out-of-band configuration.

# ---- Prompt templates ----------------------------------------------------

_PROMPT_QUICK_NAV_WALKTHROUGH = """\
You are driving NVDA through the MCP Bridge. Your job is to explore
the currently focused application the way a keyboard-only screen-reader
user would, and report what you found.

Recommended workflow (repeat until the task is complete):

1. Call `clear_speech_log` to reset the utterance buffer.
2. Call `get_focus_info` to see the currently focused UI object
   (name, role, states, containing window).
3. Decide the next single keyboard action, prefer semantic
   navigation over raw arrow keys:
     - `h` / `shift+h`   -> next / previous heading (browse mode)
     - `k` / `shift+k`   -> next / previous link
     - `f` / `shift+f`   -> next / previous form field
     - `b` / `shift+b`   -> next / previous button
     - `d` / `shift+d`   -> next / previous landmark
     - `tab` / `shift+tab` -> next / previous focusable
     - `enter` / `space` -> activate
     - `NVDA+f7`         -> element list dialog
4. Call `send_key` with that gesture.
5. Wait ~500 ms, then call `get_speech_log` to read what NVDA said
   in response.
6. If the task requires text input, call `type_text` with the string
   to be typed.

Keep every action atomic. Never guess what NVDA said - always fetch
it via `get_speech_log`. Ask `get_focus_info` again after every
action that could move focus.
"""

_PROMPT_A11Y_AUDIT = """\
You are auditing the currently focused application for accessibility
barriers, using NVDA as the ground truth for "what a screen-reader
user hears".

Method:

1. `clear_speech_log`.
2. `get_focus_info` -> record the starting focus.
3. Walk the interactive elements in tab order using `send_key` with
   `tab`. After each keystroke:
   a. `get_focus_info` -> is the new focus target sensible?
   b. `get_speech_log` (with `since_id` from the previous call) ->
      is NVDA reading out a meaningful name and role?
   c. Note any of these barriers:
        - Silent focus stop (empty name, or bare "button" with no label)
        - Missing role (element sounds like plain text but is clickable)
        - Focus escape / keyboard trap
        - Same label repeated on many controls
        - Live-region updates announced without context
4. Use `h` and `k` (quick-nav) to check heading structure and link
   labels independently of tab order.
5. Produce a report: for each barrier, quote the exact utterance NVDA
   produced (from the speech log) as evidence.
"""

_PROMPT_CAPTURE_AND_EXPLAIN = """\
The user just performed a manual action. Explain what NVDA said and
what a blind user would have understood, based only on the speech log
(do not assume visual context).

1. `get_speech_log` with `limit=20` (or more if the action was long).
2. For each utterance in order, describe:
   - What NVDA vocalised (verbatim).
   - What information that conveys to a screen-reader user
     (element name, role, state changes, positional cues).
3. Highlight any utterance that would confuse a blind user (empty
   name, missing role, ambiguous "clickable" without context).
4. Do NOT infer visual information the speech log does not contain.
"""

_PROMPT_AGENT_PLAYBOOK = """\
You are an agent driving NVDA remotely through this MCP bridge. Before
you send any input, read the full guide at resource
`nvda-mcp://docs/agent-guide`. It documents the two cursor / two mode
model, the perception loop, the quick-nav cheat sheet, and the common
traps that make a naive agent look "untrained" rather than actually
detecting real accessibility barriers.

The single most important rule: **use NVDA the way a human blind user
does.** A blind user does not press `downArrow` twenty times in a row
and only *then* listen. They press once, listen, judge, decide, then
press again. They skip content that is clearly irrelevant (a banner
they've heard before, a cookie notice, a long navigation region) as
soon as they recognise its role. They never bulk-buffer input.

Non-negotiable rules for this session:

1. **One action, then observe, then decide.** Never send more than a
   short burst of related keys (e.g. `NVDA+n` + `t` to open a specific
   submenu) before pausing to read what NVDA said and confirm focus.
   Never send 10 `downArrow`s in a `send_keys` call "to save round
   trips" — that turns you into a batch script, not a screen-reader
   user, and you will miss the exact utterance that decides your next
   move.
2. **Skip aggressively as soon as you recognise irrelevant content.**
   The moment NVDA says `banner landmark` and you are looking for
   article content, jump with `d` (next landmark) or `h` (next
   heading) — do not keep arrowing through every banner link. Cookie
   consents, navigation bars, ad-and-tracking notices are all
   "skip immediately" content once identified.
3. NEVER trust the effect of a keypress until you have called
   `get_speech_log` (with `since_id`) AND `get_focus_info` afterwards.
4. Utterances arrive over time. After a keypress, poll
   `get_speech_log` until no new entries appear for one full poll,
   THEN decide the next action. Querying too fast is the #1 source
   of "the log looks empty" false negatives.
5. Every utterance currently appears twice (pre_speech +
   pre_speechQueued). Deduplicate on `(text, floor(timestamp*10))`
   before you reason about it.
6. Prefer semantic navigation over arrow keys: `h`/`1..6` for headings,
   `d` for landmarks, `k` for links, `f`/`e`/`b`/`x`/`r` for form
   elements. Arrow keys inside a form control silently drop you into
   Focus Mode and then single-letter quick-nav STOPS WORKING - use
   `escape` or `NVDA+space` to return to Browse Mode.
7. Distinguish "I am inexperienced" from "this UI is a barrier". A
   heading you have not skipped yet, a landmark you have not used
   yet, or a skip link ("Zum Inhalt springen" / "Skip to content")
   you have not activated is NOT a barrier - it is an unused
   affordance. Only flag a barrier when the screen-reader-native
   affordances FAIL to reach the intended target.
8. **"No speech is not no effect."** When you press `enter` /
   `space` on a custom button and the log stays quiet, do NOT
   assume the widget is inert. Always cross-check both cursors:
   (a) `get_focus_info` - has the accessible name's CSS-class
   suffix flipped (e.g. `..._EXPAND` -> `..._COLLAPSE`)? (b) one
   `downArrow` in the browse buffer - does a `list with N items
   clickable ...` appear? Only if both come back unchanged is the
   widget really broken. See section 10.1 of the agent guide.
9. `send_keys` (plural) is only for bursts where the intermediate
   state does not matter: known-good menu accelerators
   (`["NVDA+n","t","a"]`), unwinding stacked dialogs
   (`["escape","escape"]`), or a form-filling shortcut
   (`["tab","tab","enter"]`). Anything that involves reading and
   reacting - walking a list, exploring an unknown widget,
   scanning form fields - must be one `send_key` at a time with a
   `get_speech_log` / `get_focus_info` observation in between.

To launch an application: press `windows`, `type_text` its name,
`enter`. Do NOT use `windows+r` from an elevated shell - the admin
Run dialog does not resolve URLs the way a normal one does.
"""

PROMPTS: List[Dict[str, Any]] = [
	{
		"name": "quick_nav_walkthrough",
		"title": "Quick-nav walkthrough of the focused app",
		"description": (
			"Guides the agent through exploring the currently focused "
			"application with screen-reader quick-nav semantics "
			"(h/k/f/b/d) instead of raw arrow keys."
		),
		"arguments": [],
		"messages": [{
			"role": "user",
			"content": {"type": "text", "text": _PROMPT_QUICK_NAV_WALKTHROUGH},
		}],
	},
	{
		"name": "accessibility_audit",
		"title": "Screen-reader accessibility audit",
		"description": (
			"Structured walk-through that produces a barrier report "
			"citing NVDA speech-log entries as evidence."
		),
		"arguments": [],
		"messages": [{
			"role": "user",
			"content": {"type": "text", "text": _PROMPT_A11Y_AUDIT},
		}],
	},
	{
		"name": "capture_and_explain",
		"title": "Explain what NVDA just said",
		"description": (
			"Reads the current speech log and explains, utterance by "
			"utterance, what a screen-reader user would have heard "
			"and understood."
		),
		"arguments": [],
		"messages": [{
			"role": "user",
			"content": {"type": "text", "text": _PROMPT_CAPTURE_AND_EXPLAIN},
		}],
	},
	{
		"name": "nvda_agent_playbook",
		"title": "NVDA agent playbook (start here)",
		"description": (
			"Compact operating rules for an agent that drives NVDA "
			"through this MCP bridge. Points at the full agent guide "
			"resource (`nvda-mcp://docs/agent-guide`) and enforces the "
			"perception loop, quick-nav priority, mode-trap avoidance, "
			"and the 'user skill vs. barrier' distinction."
		),
		"arguments": [],
		"messages": [{
			"role": "user",
			"content": {"type": "text", "text": _PROMPT_AGENT_PLAYBOOK},
		}],
	},
]

# ---- Resource contents ---------------------------------------------------
#
# Resources are read-only reference documents. Agents that support
# MCP resources (Claude Desktop, Cline) surface them in the UI and
# can attach them to prompts on demand.

_RESOURCE_AGENT_GUIDE = """\
# NVDA for MCP Agents - Operating Guide (v2)

You are an autonomous agent driving NVDA through this MCP bridge.
This document is the compressed, agent-specific digest of NVDA's
own user guide (v2026.1.1) plus the **NVDA Coach - Interactive
Screen Reader Training** add-on. It exists because a naive agent
driving NVDA will look *inexperienced* rather than actually
diagnosing accessibility problems. Read this before you send any
input.

## 0. The single most important rule: use NVDA like a human does

A blind user does **not** press `downArrow` twenty times in a row
and only *then* listen. They press once, they listen, they judge
what they just heard, they decide, then they press again. They
skip content the moment they recognise it as irrelevant. They
never bulk-buffer keystrokes.

Every rule in this guide is a corollary of this one principle.

### 0.1 One action, then observe, then decide - always

**Anti-pattern (batch-script agent):**

```
send_keys ["downArrow","downArrow","downArrow","downArrow",     # WRONG
           "downArrow","downArrow","downArrow","downArrow",
           "downArrow","downArrow","downArrow","downArrow"]
get_speech_log limit=200                                        # WRONG
# ...now try to figure out what happened
```

This is what an automation script does. It is **not** what a
screen-reader user does. It also actively hurts you: NVDA speaks
context-sensitively (a heading is spoken differently from a form
field, and both differently once you enter Focus Mode); by the
time you read the log you have lost the mapping "which utterance
belongs to which keypress", so you cannot even tell when a mode
switch happened mid-run.

**Correct pattern (screen-reader-user agent):**

```
send_key   {"gesture": "downArrow"}          # one step
poll get_speech_log(since_id=last) until settled
get_focus_info                                # confirm where you are
reason -> was this the target? relevant? or skip?
send_key   {"gesture": <next single action>}  # one step
...
```

`send_keys` (plural) is for short, semantically-atomic bursts
where the intermediate state is not observable and is not worth
observing: `NVDA+n` -> `t` -> `a` to reach "Add-on store" through
the NVDA menu, or `escape`, `escape` to unwind two nested dialogs.
It is **not** for "walk 12 rows down". If you find yourself
building an array of `downArrow`/`tab`/`h` entries, stop and send
them one at a time instead - it is slower per round trip, but it
is dramatically faster in terms of *task completion*, because you
will not overshoot the target or miss the exact utterance that
tells you you have arrived.

### 0.2 Skip aggressively - do not read what you do not need

A screen-reader user can read faster than a sighted user in one
specific sense: **they don't read what they don't need**. As soon
as NVDA says `banner landmark` and the task is "find the article
body", the user does not keep pressing `downArrow` through every
navigation link. They hit `d` (next landmark) or `h` (next
heading) or `enter` on a "Skip to content" link, and they are
gone.

Concrete decision recipes:

- Speech log says `banner landmark` and task target is content
  -> immediately `d` (next landmark) or open Elements List
  (`NVDA+f7`, filter to Headings, jump to H1).
- Speech log says `navigation landmark ... list with N items`
  and you are looking for content -> `d` past it.
- Speech log says `same page link Zum Inhalt springen` /
  `Skip to main content` -> **use it**. `enter` on it (in
  Browse Mode: `k` to land on it first, then `enter`).
- Speech log announces a cookie banner or tracking notice -> use
  `b` (next button), find "Ablehnen" / "Reject" / "Only necessary",
  `enter`, done. Do not read the notice content.
- Speech log announces the same repeated phrase >3 times in a row
  (e.g. an autonomous `aria-live` polling widget) -> ignore all
  subsequent occurrences; they carry no new information.

If you find yourself reading every utterance start to end, you
have already lost the pace of a real screen-reader user. Ask
"is this utterance moving me toward my goal?" - if no, skip.

**On the Elements List (`NVDA+f7`) as a shortcut.** It is a
legitimate tool and it is mentioned throughout this guide, but it
is NOT the primary navigation pattern of a screen-reader native.
A blind user reaches for `h`, `d`, `k`, `b`, `tab` / `shift+tab`
first, and only falls back to the Elements List when linear
navigation is genuinely stuck. When the goal is a realistic user
path (studies, audits, "would a real user find this?"), exhaust
quick-nav and Tab / Shift+Tab before opening the Elements List.
Using it as the default first move short-circuits exactly the
observation you are supposed to make.

### 0.3 Never call `send_keys` for exploratory navigation

Reserve `send_keys` for exactly three use cases:

1. Semantically-atomic menu drilling with well-known accelerators:
   `["NVDA+n","t","a"]` (Add-on store), `["NVDA+n","p","s"]`
   (Preferences -> Settings).
2. Unwinding known-nested state: `["escape","escape","escape"]`
   to close 3 stacked dialogs.
3. Typing structured input where the intermediate state is not
   interesting: use `type_text` for actual text, and `send_keys`
   for a form-filling shortcut like `["tab","tab","enter"]`.

For anything that involves *reading and reacting* - walking a
list, exploring headings, scanning form fields, browsing table
cells - use `send_key` singular, one press at a time.

### 0.4 Practical time budget

A rough rhythm to aim for:

- ~1 `send_key` every 1-3 turns of the agent loop.
- After each `send_key`: 1 `get_speech_log(since_id=...)` (often
  polled 2-3 times to catch late-arriving utterances) plus at
  most 1 `get_focus_info`.
- The moment `get_speech_log` returns "no new entries for one
  full poll", stop polling and decide.
- Never send a second `send_key` before the previous one has
  produced its last utterance. If NVDA is still saying
  "Loading page" from the last action, the current action is
  wasted.

If your task takes 30 minutes because you spent 25 of them
skipping content and 5 acting on the right 6 elements, that is
correct behavior - it is what a real user does. If your task
takes 5 minutes because you blasted through 200 keys and hoped
for the best, you probably completed the wrong task.

## 1. The three-layer keyboard command model

Every gesture belongs to exactly one of three layers. Knowing which
layer a gesture is on tells you where it goes, what it does, and
where to look for its effect.

1. **Windows / OS layer** - `tab`, `shift+tab`, `enter`, `space`,
   `escape`, `alt+tab`, `alt+f4`, `control+c/v/x`, `windows+d`,
   arrow keys inside a control, `home`/`end`, `pageUp`/`pageDown`,
   any single character typed via `type_text`. Works in every
   program. The bridge injects it via `keybd_event`.
2. **Application layer** - `control+l` (address bar), `control+n`
   (new document in Word), `F5` (refresh in browser), `control+f`
   (browser Find), `control+alt+arrow` (table cell navigation in
   HTML/Word). Also injected as OS keystrokes; the application
   decides how to react.
3. **NVDA / screen-reader layer** - `NVDA+t`, `NVDA+n`, `NVDA+f7`,
   every browse-mode quick-nav letter, every object-navigation
   command, `NVDA+1` (Input Help), `NVDA+space` (mode toggle).
   These take **no action in the application** - they only inform
   NVDA and produce speech. The bridge routes them directly through
   `inputCore.manager.executeGesture()`, bypassing the OS keyboard
   stack entirely (see section 13 for why this matters).

The agent does not need to pick a route manually - the bridge
detects layer 3 by looking at whether the parsed gesture has an
NVDA `.script` bound. But knowing the mental model helps you
predict what a gesture will (and will not) do.

## 2. The two-cursor / two-mode mental model

NVDA maintains three independent cursors:

- **System focus** - the OS-level focused control. `get_focus_info`
  returns this. Moved by `tab`, `shift+tab`, `alt+tab`, arrows
  inside menus, mouse clicks.
- **Virtual browse-mode cursor** - a separate reading cursor NVDA
  overlays on browse-mode documents (web pages, PDFs, HTML mail).
  Decoupled from system focus. Quick-nav letters (`h`/`d`/`k`/...)
  move it.
- **Navigator object** - a third, orthogonal cursor for exploring
  the accessibility tree of the current window (section 5). Moving
  it does NOT change focus and does NOT act on the app.

Independently, in browse-mode documents NVDA is in one of two
INPUT modes:

- **Browse Mode** (default on page load): single letters do quick
  nav. Arrows move the virtual cursor.
- **Focus Mode**: keystrokes go straight to the control (edit
  boxes, radio groups, comboboxes). Single-letter quick-nav is
  DISABLED - typing `h` types the letter h.

NVDA auto-toggles into Focus Mode when focus enters a form control.
Manual toggle: `NVDA+space`. Escape hatch: `escape`.

**Rule of thumb:** if `get_focus_info` returns a role of
`EDITABLETEXT`, `COMBOBOX`, `RADIOBUTTON`, `CHECKBOX`, `SLIDER`, or
`SPINBUTTON` **without** `READONLY` in `states`, assume Focus Mode
is active and quick-nav will do nothing until you `escape`.

**Corollary - read-only edit controls are content, not traps:** if
the role is `EDITABLETEXT` but `READONLY` and `MULTILINE` are BOTH
in `states` (typical for Windows "About" dialogs, help viewers,
release-note panes, and the NVDA Coach lesson panels), the control
holds a *displayed document*, not an input trap. Its full text is
returned by `get_focus_info` in the `value` field - one call, no
line-by-line arrow reading needed. See section 4.

## 3. Desktop layout vs. Laptop layout

NVDA has TWO keyboard-layout modes chosen in Preferences ->
Settings -> Keyboard -> "Keyboard layout" combo box. This is a
**software mapping**, independent of physical hardware.

- **Desktop layout** binds many NVDA commands to the numeric keypad
  (`NVDA+numpad4/5/6/7/8/9/2/3/1/Minus/...`).
- **Laptop layout** binds the same commands to `NVDA+letter` or
  `NVDA+shift+letter` combinations for keyboards without a numpad.

**If a gesture "does nothing" and it uses `numpad*`, the most
likely cause is that NVDA is set to laptop layout.** Vice versa
for laptop combos on a desktop-layout install.

Commands that DIFFER between layouts (send the right one for the
active layout, or send both in sequence and see which produces
speech):

| Purpose                              | Desktop            | Laptop                    |
|--------------------------------------|--------------------|---------------------------|
| Say-all from cursor                  | `NVDA+downArrow`   | `NVDA+A`                  |
| Report current navigator object      | `NVDA+numpad5`     | `NVDA+shift+o`            |
| Move to containing object (parent)   | `NVDA+numpad8`     | `NVDA+shift+upArrow`      |
| Move to previous object (sibling)    | `NVDA+numpad4`     | `NVDA+shift+leftArrow`    |
| Move to next object (sibling)        | `NVDA+numpad6`     | `NVDA+shift+rightArrow`   |
| Move to first contained object       | `NVDA+numpad2`     | `NVDA+shift+downArrow`    |
| Prev / next in flattened view        | `NVDA+numpad9/3`   | `NVDA+shift+[` / `NVDA+shift+]` |
| Sync navigator to focus              | `NVDA+numpadMinus` | `NVDA+backspace`          |
| Sync focus to navigator (once)       | `NVDA+shift+numpadMinus` | `NVDA+shift+backspace` |
| Switch review mode next / previous   | `NVDA+numpad7/1`   | `NVDA+pageUp` / `NVDA+pageDown` |
| Report review cursor location        | `NVDA+shift+numpadDelete` | `NVDA+shift+delete` |

Commands that are the **SAME on both layouts** (these always work):

- `NVDA+n` (menu), `NVDA+t` (title), `NVDA+tab` (describe focus),
- `NVDA+upArrow` (read current line), `NVDA+b` (read whole
  window), `NVDA+end` (status bar),
- `NVDA+f` (formatting), `NVDA+k` (link URL), `NVDA+f12` (time),
- `NVDA+shift+B` (battery), `NVDA+shift+D` (audio ducking),
- `NVDA+f7` (Elements List), `NVDA+control+f` (Find),
- `NVDA+space` (Browse/Focus toggle), `NVDA+1` (Input Help),
- `NVDA+shift+c` (NVDA Coach lesson picker, if installed),
- All Browse-Mode quick-nav letters (`h`/`d`/`k`/`f`/`e`/`b`/...),
- `control+alt+arrow` (table cell navigation).

## 4. The canonical perception loop

Every action follows this loop. Skipping any step is the #1 cause
of "the bridge doesn't work" false negatives:

```
1. clear_speech_log()   OR   remember last since_id
2. send_key(...) / send_keys / type_text
3. get_focus_info()
      -> if role is EDITABLETEXT with READONLY+MULTILINE in states,
         `value` already contains the full text of the pane. STOP.
4. poll get_speech_log(since_id=...) repeatedly
   until no new entries arrive for one full poll
   (utterances trickle in over 5-50 s on verbose pages)
5. reason -> next action
```

**Why check `get_focus_info` first?** For dialogs, help panels,
lesson panels, "About" boxes, and every other read-only multi-line
edit control, the whole rendered text is served in one call. You
save 20+ arrow keystrokes and the associated speech-log parsing.

**Why the poll loop for browse-mode documents?** NVDA renders
speech at ~1 utterance per few hundred ms. A Wikipedia
article's donation banner (autonomous `aria-live="polite"`
announcements) drips in over ~50 s. Querying `get_speech_log` once,
200 ms after the keypress, will show a half-empty log.

## 5. Object Navigation - the fallback when Tab and quick-nav fail

Some controls are not reachable by `tab` (Windows Tab-order gaps),
not reachable by browse-mode quick-nav (custom widgets without
proper ARIA roles - popup menus, custom dropdowns, canvas-drawn
controls), and never receive keyboard focus at all (decorative
labels, split-panel dividers, screen-only annotations). For these,
NVDA exposes the entire accessibility tree via **object
navigation**.

**Mental model:** the current window is a tree. The window itself
is the root. Panels, toolbars, menus are the next level.
Individual controls (buttons, edit fields, checkboxes) are the
leaves. NVDA can walk any node.

The **navigator object** is a fourth cursor (in addition to system
focus, virtual browse cursor, and caret). Moving it does not
change focus, does not click, does not change any application
state - it is a read-only exploration cursor.

Full command set (desktop / laptop columns from section 3):

- **Report** the current navigator object: `NVDA+numpad5` /
  `NVDA+shift+o`. Press twice quickly = spell the name. Press
  three times = copy name+value to clipboard (useful when you need
  to extract a value the speech log has already scrolled past).
- **Parent** (containing object): `NVDA+numpad8` /
  `NVDA+shift+upArrow`.
- **First child** (contained object): `NVDA+numpad2` /
  `NVDA+shift+downArrow`.
- **Previous / next sibling**: `NVDA+numpad4` / `NVDA+numpad6` in
  desktop; `NVDA+shift+leftArrow` / `NVDA+shift+rightArrow` in
  laptop.
- **Flattened prev/next** (skip the hierarchy, walk the tree in
  reading order): `NVDA+numpad9` / `NVDA+numpad3` in desktop;
  `NVDA+shift+[` / `NVDA+shift+]` in laptop.
- **Sync navigator to focus** (jump the navigator to wherever the
  system focus currently is): `NVDA+numpadMinus` / `NVDA+backspace`.
- **Sync focus to navigator** (move system focus to the object the
  navigator is on - lets you *reach* an otherwise-unreachable
  control): `NVDA+shift+numpadMinus` / `NVDA+shift+backspace`.
  Press twice to also move the caret to the review position.

**Recipe for reaching a custom widget (e.g. an unlabelled
sort-dropdown that Tab and quick-nav can't reach):**

```
send_key    {"gesture": "NVDA+numpadMinus"}   # sync navigator to focus
send_key    {"gesture": "NVDA+numpad5"}       # what am I on?
send_key    {"gesture": "NVDA+numpad2"}       # descend
send_key    {"gesture": "NVDA+numpad6"}       # next sibling; repeat until found
send_key    {"gesture": "NVDA+numpad5"}       # confirm target
send_key    {"gesture": "NVDA+shift+numpadMinus"}  # move focus here
send_key    {"gesture": "enter"}              # activate
```

Object navigation is what a screen-reader native reaches for when
"the Tab order won't take me there." Treat it as the tool of last
resort for **discovery**, and as the tool of *first* resort when
you already know Tab won't reach a target.

## 6. Table cell navigation

For HTML / Word / Excel-like tables, cell-by-cell navigation is a
dedicated command family that works the same on both layouts:

| Direction         | Gesture                    |
|-------------------|----------------------------|
| Next cell in row  | `control+alt+rightArrow`   |
| Prev cell in row  | `control+alt+leftArrow`    |
| Cell below (col)  | `control+alt+downArrow`    |
| Cell above (col)  | `control+alt+upArrow`      |

NVDA speaks the cell content **and** its row/column position, so
you don't have to keep separate track. Prefer this to
`NVDA+downArrow` say-all for structured data (schedules, prices,
comparison tables) - say-all flattens rows and loses column
boundaries.

## 7. Quick-nav cheat sheet (Browse Mode only)

Single letters in a browse-mode document. Add `shift+` for
backwards.

| Key    | Target                                       |
|--------|----------------------------------------------|
| `h`    | next heading (any level)                     |
| `1..6` | next heading at that specific level          |
| `d`    | next landmark (main / navigation / banner)   |
| `k`    | next link                                    |
| `u`    | next unvisited link                          |
| `v`    | next visited link                            |
| `f`    | next form field (any type)                   |
| `e`    | next edit field                              |
| `b`    | next button                                  |
| `x`    | next checkbox                                |
| `r`    | next radio button                            |
| `c`    | next combo box                               |
| `t`    | next table                                   |
| `l`    | next list                                    |
| `i`    | next list item                               |
| `g`    | next graphic                                 |
| `p`    | next text paragraph                          |
| `q`    | next block quote                             |
| `s`    | next separator                               |
| `m`    | next frame                                   |
| `a`    | next annotation (comment / revision)         |
| `o`    | next embedded object                         |
| `w`    | next spelling error                          |
| `,`    | past end of current container (list, table)  |
| `shift+,` | to start of current container             |

## 8. Elements List and Find - page-wide search

**`NVDA+f7`** opens the Elements List dialog - a *filterable* table
of contents for the current page. Same on both layouts. Inside:

- `Alt+H` (Links), `Alt+L` (Headings), `Alt+F` (Form fields),
  `Alt+B` (Buttons) toggle the four filter radios.
- The type-ahead edit field filters the list by substring.
- Arrow keys walk the filtered tree.
- `Enter` on any entry jumps the virtual cursor to that element
  in the document.

Use this **first** when looking for a specific element on a large
page - it's faster than iterating with `h`/`k`/`b` and it works
even when the element has an unusual role.

**`NVDA+control+f`** opens NVDA's Find dialog. Important caveat:
this NVDA script is bound to the browse-mode virtual buffer. When
system focus is on a form control (edit box, combo box) NVDA does
not intercept the chord and `Ctrl+F` reaches the application
(browser Find bar in Edge, for example). Workarounds:

1. `escape` first to leave Focus Mode, then `NVDA+control+f`.
2. Or just use `NVDA+f7` (Elements List) - it works everywhere.

## 9. Skip links and landmarks - use them BEFORE anything else

Most modern web pages start with either:

- A `"Zum Inhalt springen"` / `"Skip to main content"` **same-page
  link** at the very top. In the speech log it looks like
  `same page link Zum Inhalt springen`. Press `enter` on it to
  jump to the article body.
- A `main` **landmark** wrapping the actual content. `d` navigates
  to it. The speech log announces
  `main landmark heading level 1 X` once you land on the H1.

A good agent uses these first. Fighting through a banner heading
by heading is what an untrained sighted person does with a screen
reader they've never used - not what a screen-reader native does.

## 10. Common mode traps and how to escape

| Trap                                          | Signal                          | Fix                     |
|-----------------------------------------------|---------------------------------|-------------------------|
| Landed in an edit box, quick-nav dead         | `EDITABLETEXT` in `states`, `READONLY` NOT in `states` | `escape` or `NVDA+space` |
| Landed in a Wikipedia sidebar radio group     | `radio button ... checked` in log | `escape`, then `d`     |
| `p` (paragraph) does nothing                  | Focus Mode is active             | `NVDA+space` -> Browse  |
| `NVDA+numpad*` gesture "does nothing"         | Silent, no log entry             | NVDA is on Laptop layout - use `NVDA+shift+letter` alternative |
| `NVDA+control+f` opens browser Find not NVDA Find | You are in Focus Mode      | `escape` first, or use `NVDA+f7` |
| Custom widget won't respond to arrow / Enter  | `clickable` in log, no proper role | Object Navigation recipe (section 5) |
| Custom dropdown / disclosure trigger with a CSS-class in its name | Accessible name ends in `_EXPAND` / `_COLLAPSE` / `_OPEN` / `_ACTIVE`; no `EXPANDED` in `states` | State is encoded in the class name, not in ARIA. `aria-expanded` is missing. Verify by section 10.1 recipe, do NOT declare it broken from silence alone. |
| Popup options unreachable via `tab` after opening a custom dropdown | Enter changed the class suffix from `_EXPAND` to `_COLLAPSE`, but `tab` jumps to the next filter | Options are in the DOM without `tabindex`. Move the browse cursor: one `downArrow` (or `l` for next list) surfaces them as `list with N items clickable X`. |
| Focus jumped to Desktop after `Win+R` + URL   | `appModule: explorer` on `Recycle Bin` | Elevated Run dialog does NOT resolve URLs. Use Start menu instead. |

## 10.1 Custom React-style widgets (the "silent button" trap)

Modern shops, product filters and one-page apps ship custom
disclosure buttons that look like proper buttons but are neither
comboboxes nor menu buttons. Symptoms you will see in the log
and in `get_focus_info`:

- Accessible name contains an underscored CSS class, e.g.
  `Sortieren MAK_REACT_EXPAND`, `Filter TS_REACT_COLLAPSE`,
  `Menu HEADER_OPEN`. The class is the state indicator.
- Role is `BUTTON` but `states` does NOT contain `EXPANDED`.
- Pressing `enter` or `space` produces **no speech at all**.
- `alt+downArrow` (native combobox key) does nothing.
- The next `tab` jumps to the following control, as if the button
  did nothing.

None of that means the button is broken. Almost always the click
handler ran, the DOM updated, and the popup is visible - it just
did not announce itself. The confirmation procedure is:

1. After `enter` on the button, call `get_focus_info` and inspect
   the class suffix in `name`. `..._EXPAND` -> `..._COLLAPSE`
   means the widget did toggle.
2. Send exactly ONE `downArrow`. This moves the virtual browse
   cursor past the button into the newly-rendered popup content.
3. `get_last_spoken` should now announce something like
   `list with N items clickable <first option>`. That IS the
   options list.
4. Continue with `downArrow` through the options and `enter` on
   the desired one. Do NOT use `tab` inside the popup - React
   often forgets `tabindex` on the option rows, so `tab` skips
   the popup entirely.
5. After activating an option the widget usually closes silently.
   Verify the effect by moving to a stable landmark (H1, main)
   and reading the first following content, not by expecting an
   announcement.

**"No speech is not no effect."** For custom widgets, always
cross-check both cursors after a key: the focus (name / class
suffix / states via `get_focus_info`) AND one browse-cursor step
via `downArrow`. Only after both are silent and unchanged is the
widget genuinely inert.

## 11. Launching an application

The `Win+R` Run dialog inherits the elevation level of the
currently focused window. From an elevated PowerShell, `Win+R`
opens an **admin Run dialog** that treats input as a program path
only - a URL is NOT resolved to the default browser.

**Canonical launcher pattern:**

```
send_key    {"gesture": "windows"}          # open Start menu search
type_text   {"text": "edge"}                # or "chrome", "firefox", ...
send_key    {"gesture": "enter"}
poll get_speech_log until settled
get_focus_info                              # confirm appModule
```

**For URLs in an already-open browser:**

```
send_key    {"gesture": "control+l"}        # focus address bar
type_text   {"text": "https://..."}
send_key    {"gesture": "enter"}
```

## 12. Reporting system information

Use these self-report gestures to make NVDA state something in the
speech log:

| Gesture              | Effect                                             |
|----------------------|----------------------------------------------------|
| `NVDA+t`             | Speak window title                                 |
| `NVDA+tab`           | Describe current focus (name/role/state)           |
| `NVDA+upArrow`       | Read current line (2x = spell, 3x = phonetic)      |
| `NVDA+downArrow` / `NVDA+A` | Say all from cursor (desktop / laptop layout) |
| `NVDA+b`             | Read the whole active window / dialog              |
| `NVDA+end`           | Read status bar                                    |
| `NVDA+f`             | Report text formatting at cursor                   |
| `NVDA+k`             | Report link destination URL at cursor              |
| `NVDA+f12`           | Report time (2x = date)                            |
| `NVDA+shift+B`       | Report battery status                              |
| `NVDA+numpad5` / `NVDA+shift+o` | Report current navigator object         |

Note that `NVDA+tab` is very close to `get_focus_info` - use
`get_focus_info` when you can (it returns structured JSON without
having to parse a speech utterance), and `NVDA+tab` when you need
NVDA's own rendering of the state for a report.

## 13. Interpreting the speech log

Utterances follow a `<role> <state?> <name>` pattern. Common
prefixes and what they mean:

- `heading level N X`             - a level-N heading with text X
- `main landmark heading level 1 X` - **article/page title** (arrived at target)
- `banner landmark`               - top page banner (usually skippable)
- `navigation landmark`           - navigation region
- `search landmark form ...`      - search widget
- `same page link X`              - an in-page anchor link
- `link X`, `visited link X`      - regular / previously visited link
- `list with N items`             - the virtual cursor entered a list
- `out of list`                   - the virtual cursor exited a list
- `edit ... Alt+o selected X`     - edit control with pre-selected text
- `edit ... protected ...`        - a password field
- `radio button not checked` / `radio button checked` - radio state
- `check box focused not checked` - checkbox with focus and unchecked
- `clickable`                     - element has a click handler but no
  proper role (weak signal, sometimes a barrier)
- `graphic X`                     - image with alt text X (or filename
  if no alt)
- `sub Menu` / `subMenu`          - a submenu marker
- `1 of N`                        - position in a listbox / menu
- `row X column Y`                - table cell position after
  `control+alt+arrow` movement

If NVDA says `edit`, `combo box`, `button`, ... **without a name**,
that is a real accessibility barrier - the developer forgot to
label the control. Cite the exact utterance as evidence.

## 14. Duplicate utterances

Every utterance currently appears twice in `get_speech_log`
because we register on both `pre_speech` and `pre_speechQueued`
extension points (defensive fallback from the v0.1.0
BoundMethodWeakref bug). Deduplicate on
`(text, floor(timestamp * 10))` before reasoning.

## 15. The "inexperienced user vs. real barrier" distinction

Before flagging something as an accessibility barrier, check:

- Did you use the **skip link** if the page provided one?
- Did you try `d` (next landmark) before iterating with `h`?
- Are you actually in Browse Mode? (`get_focus_info` -> role)
- Is the "annoying" content an autonomous `aria-live` update
  (donation banner, cookie notice) you can simply skip past?
- Have you tried `NVDA+f7` (Elements List) for a filterable
  overview?
- Have you tried **Object Navigation** (section 5) for a widget
  that Tab and quick-nav couldn't reach?
- After `enter` / `space` on a custom button that stayed silent,
  did you check BOTH cursors (`get_focus_info` for a class-suffix
  toggle **and** one `downArrow` in the browse buffer) before
  concluding the widget is broken? See section 10.1.

A barrier is what remains when **all four native strategies** -
skip link, landmarks, Elements List, and Object Navigation - have
been used and STILL fail. Everything else is user skill (yours).

## 16. Input Help mode

`NVDA+1` (top-row `1`, not numpad) toggles Input Help mode. While
active, every keystroke NVDA receives is *described* rather than
executed - so an agent that experimentally sends
`NVDA+shift+x` while Input Help is on will get the *description*
of that gesture in the speech log without triggering the action.

This is useful for probing an unknown installed add-on's gesture
bindings without side effects. Remember to send `NVDA+1` again to
exit Input Help before continuing normal operation.

## 17. Speech Viewer parity

`get_speech_log` returns exactly what NVDA's built-in Speech Viewer
window (Tools -> Speech viewer) would show a sighted observer. It
is the complete ground truth for "what a screen-reader user
hears". You cannot see anything a blind NVDA user cannot hear via
this log.

If you want to reason about visual layout, formatting, or colours
that were NOT spoken, use `NVDA+f` at the cursor to force NVDA to
speak the formatting, then read the log. Do not infer visual
information the log does not contain.

## 18. OS keyboard injection vs. NVDA script dispatch (internals)

The `send_key` / `send_keys` tools understand two categories of
gestures and route them differently under the hood:

- **NVDA-native commands** (`NVDA+n`, `NVDA+space`, `NVDA+t`,
  `NVDA+f7`, `NVDA+downArrow`, every browse-mode quick-nav letter,
  every object-navigation command, ...) are dispatched **directly**
  through `inputCore.manager.executeGesture()`. They never leave
  NVDA and are not visible to the OS. This is the only way to
  actually trigger NVDA's own scripts, because
  `KeyboardInputGesture.send()` wraps its `keybd_event` calls in
  `ignoreInjection()`, which makes NVDA's own low-level hook drop
  the injected keys before they reach `executeGesture`.

- **Pure OS/app keystrokes** (`tab`, `control+l`, `enter`,
  `windows+d`, `alt+f4`, literal letters typed via `type_text`,
  `control+alt+arrow` for tables, ...) fall through to
  `KeyboardInputGesture.send()` and are injected as real
  `keybd_event` Windows messages.

The bridge picks the route automatically by checking whether the
resulting `KeyboardInputGesture` has an NVDA `.script` bound to it.
An agent does not need to know the distinction - the same gesture
string works for both categories. In particular, all the
self-report gestures listed in section 12 take the direct-dispatch
path and will show up as speech-log entries even though no
OS-level keystroke was ever emitted.

**Focus-context caveat:** `NVDA+control+f` (Find) is bound at the
NVDA layer only inside browse-mode documents. When system focus is
on a form control, NVDA does not intercept the chord and the
resulting keystroke reaches the application (browser Find dialog).
This is intentional NVDA behavior, not a bridge bug. Section 8
covers workarounds.

## 19. If NVDA Coach is installed - learn interactively

If the Add-on store (`NVDA+n` -> `t` -> `a`) shows **NVDA Coach**
by Tony Gebhard, the entire course is available to an MCP agent
just as it is to a human. Launch with `NVDA+shift+c`. The lesson
picker is a `SysTreeView32` with 8 chapters and 45 lessons total.
Inside an open lesson: `enter` advances a step, `F1` repeats the
current instruction, `F2` gives a hint, `F3` skips a step, `Ctrl+N`
moves to the next lesson, `Ctrl+B` to the previous, `Ctrl+R`
restarts, and `escape` 3x closes the whole course. Lesson-complete
and lesson-picker panes are read-only `EDITABLETEXT` controls, so
`get_focus_info` gives you their full text in one call (section 4).
"""

_RESOURCE_API_OVERVIEW = """\
# NVDA MCP Bridge - API Reference

**Endpoint:** POST http://127.0.0.1:8765/mcp (Streamable HTTP, JSON-RPC 2.0)
**Health:**   GET  http://127.0.0.1:8765/health -> {"status":"ok"}
**Debug:**    GET  http://127.0.0.1:8765/debug/status -> JSON diagnostic snapshot

## Supported MCP methods

- `initialize`     - handshake
- `ping`           - keep-alive
- `tools/list`     - enumerate tools
- `tools/call`     - invoke a tool by name
- `prompts/list`   - enumerate prompt templates
- `prompts/get`    - fetch one prompt template
- `resources/list` - enumerate reference documents
- `resources/read` - fetch one reference document
- `notifications/*` - accepted (no-op)

## Tools

| Name               | Input (JSON-Schema shorthand)             | Output shape                                |
|--------------------|-------------------------------------------|---------------------------------------------|
| `get_speech_log`   | `{limit?:int, since_id?:int}`             | `{entries:Entry[], count:int, since_id:int}`|
| `get_last_spoken`  | `{}`                                      | `{entry: Entry \\| null}`                    |
| `clear_speech_log` | `{}`                                      | `{ok:true}`                                 |
| `send_key`         | `{gesture:str}`                           | `{ok:true, gesture:str}`                    |
| `send_keys`        | `{gestures:str[], delay_ms?:int}`         | `{ok:true, sent:int}`                       |
| `type_text`        | `{text:str, delay_ms?:int}`               | `{ok:true, sent:int, requested:int}`        |
| `get_focus_info`   | `{}`                                      | `{name, value, description, role, states[], windowClassName, windowText, appModule}` |
| `get_server_info`  | `{}`                                      | `{name, version, host, port, path, auth_enabled, input_backends[]}` |

`Entry` = `{id:int, timestamp:float, text:str}`.

## Tool return contract

Every tool returns a **JSON object** wrapped in an MCP `CallToolResult`
with both a text block (JSON-serialised for backward compatibility)
and `structuredContent` set to the same object. This is required by
the MCP spec (`structuredContent` must be an object) and validated
strictly by the reference `mcp` SDK's pydantic models.

## Prompts

The server ships three prompt templates that agents can inject into
their own context via `prompts/get`:

- `quick_nav_walkthrough` - step-by-step guidance for exploring an
  app the way a screen-reader user would (h/k/f/b/d, not arrows).
- `accessibility_audit` - structured barrier report driven by
  speech-log evidence.
- `capture_and_explain` - explain the current speech log entry by
  entry.

## Gesture syntax

Gesture strings follow NVDA's own naming:

- Letters/digits: `"a"`, `"1"`
- Named keys: `"enter"`, `"escape"`, `"tab"`, `"space"`,
  `"upArrow"`, `"downArrow"`, `"leftArrow"`, `"rightArrow"`,
  `"home"`, `"end"`, `"pageUp"`, `"pageDown"`, `"backspace"`,
  `"delete"`, `"insert"`, `"f1"` .. `"f24"`
- Modifier combos: `"control+a"`, `"shift+tab"`,
  `"control+shift+end"`, `"NVDA+f7"`, `"windows+d"`
- Literal `+`: `"plus"`
"""

_RESOURCE_GESTURE_REFERENCE = """\
# NVDA gesture reference

Every argument to `send_key` and every entry of the `gestures` array
in `send_keys` is a NVDA-style gesture string.

## Modifier tokens
- `control`  (or `ctrl`)
- `shift`
- `alt`
- `windows` (or `win`)
- `NVDA`    (the NVDA modifier key, usually Insert or Caps Lock)

Modifiers are combined with `+`. Order does not matter but keep it
consistent for readability: `"control+shift+end"`, `"NVDA+f7"`.

## Common keys
- Letters and digits: `a`, `b`, ..., `1`, `2`, ...
- Navigation: `upArrow`, `downArrow`, `leftArrow`, `rightArrow`,
  `home`, `end`, `pageUp`, `pageDown`
- Editing: `backspace`, `delete`, `enter`, `space`, `tab`, `escape`,
  `insert`
- Function keys: `f1` .. `f24`
- Literal plus sign: `plus`

## NVDA-specific (browse mode)
When focus is inside a browse-mode document (browser page, PDF,
richtext viewer), single-letter gestures navigate by element type:

| Gesture     | Effect                          |
|-------------|---------------------------------|
| `h` / `shift+h` | next / previous heading      |
| `k` / `shift+k` | next / previous link         |
| `f` / `shift+f` | next / previous form field   |
| `b` / `shift+b` | next / previous button       |
| `d` / `shift+d` | next / previous landmark     |
| `t` / `shift+t` | next / previous table        |
| `l` / `shift+l` | next / previous list         |
| `NVDA+f7`   | open element list dialog       |
| `NVDA+space`| toggle focus mode / browse mode|

## Global NVDA gestures worth knowing
| Gesture     | Effect                          |
|-------------|---------------------------------|
| `NVDA+t`    | speak window title             |
| `NVDA+f`    | report formatting              |
| `NVDA+downArrow` | say all                   |
| `NVDA+n`    | open the NVDA menu             |
| `NVDA+q`    | quit NVDA (be careful)         |
"""

_RESOURCE_WORKFLOWS = """\
# Sample workflows

## 1. Read the currently focused control

```
clear_speech_log()
get_focus_info()
send_key({"gesture": "NVDA+tab"})   # NVDA reports focus
sleep 0.5s
get_speech_log({"limit": 20})
```

## 2. Walk a form in tab order

```
clear_speech_log()
loop:
    send_key({"gesture": "tab"})
    sleep 0.3s
    focus = get_focus_info()
    log   = get_speech_log({"since_id": last_seen_id})
    if focus.role == "editable_text":
        type_text({"text": "..."})
```

## 3. Explore the headings of a page in the browser

```
send_key({"gesture": "NVDA+f7"})   # open element list dialog
sleep 0.5s
get_speech_log({"limit": 50})
send_key({"gesture": "escape"})
```

## 4. Barrier detection on an anonymous UI

```
clear_speech_log()
for _ in range(20):
    send_key({"gesture": "tab"})
    sleep 0.3s
focus_seq   = [get_focus_info() every step]
speech_seq  = get_speech_log({"limit": 200})
# Analyse: any focus stop where the corresponding
# utterance had no name / no role / duplicate label
# is a candidate barrier.
```
"""

RESOURCES: List[Dict[str, Any]] = [
	{
		"uri": "nvda-mcp://docs/agent-guide",
		"name": "NVDA agent operating guide (start here)",
		"description": (
			"Agent-specific digest of the NVDA user guide: the two "
			"cursor / two mode model, the perception loop, quick-nav "
			"cheat sheet, mode-trap escape recipes, application "
			"launcher patterns, speech-log interpretation, and the "
			"'inexperienced user vs. real barrier' distinction. "
			"Read this before sending any input."
		),
		"mimeType": "text/markdown",
		"_text": _RESOURCE_AGENT_GUIDE,
	},
	{
		"uri": "nvda-mcp://docs/api",
		"name": "API reference",
		"description": (
			"Full endpoint + method + tool + return-shape reference "
			"for the NVDA MCP Bridge."
		),
		"mimeType": "text/markdown",
		"_text": _RESOURCE_API_OVERVIEW,
	},
	{
		"uri": "nvda-mcp://docs/gestures",
		"name": "NVDA gesture syntax",
		"description": (
			"Complete list of gesture strings accepted by `send_key`, "
			"`send_keys`, and `type_text` (as literal characters), "
			"including quick-nav single-letter gestures."
		),
		"mimeType": "text/markdown",
		"_text": _RESOURCE_GESTURE_REFERENCE,
	},
	{
		"uri": "nvda-mcp://docs/workflows",
		"name": "Sample workflows",
		"description": (
			"Four concrete example workflows an agent can follow: "
			"read focus, walk a form, explore headings, detect barriers."
		),
		"mimeType": "text/markdown",
		"_text": _RESOURCE_WORKFLOWS,
	},
]


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

class ToolDef:
	"""Single registered tool."""

	def __init__(
		self,
		name: str,
		description: str,
		handler: Callable[..., Any],
		input_schema: Dict[str, Any],
	) -> None:
		self.name = name
		self.description = description
		self.handler = handler
		self.input_schema = input_schema


class ToolRegistry:
	def __init__(self) -> None:
		self._tools: Dict[str, ToolDef] = {}

	def register(self, tool: ToolDef) -> None:
		self._tools[tool.name] = tool

	def get(self, name: str) -> Optional[ToolDef]:
		return self._tools.get(name)

	def as_list(self) -> List[Dict[str, Any]]:
		return [
			{
				"name": t.name,
				"description": t.description,
				"inputSchema": t.input_schema,
			}
			for t in self._tools.values()
		]


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def _build_tools(ctx: ServerContext) -> ToolRegistry:
	"""Instantiate the eight v1 tools bound to ``ctx``."""
	reg = ToolRegistry()

	def _check_auth() -> None:
		try:
			ctx.auth.authenticate(headers=None)
		except AuthError as exc:
			raise PermissionError(str(exc)) from exc

	# --- Speech log tools ---------------------------------------------------

	def get_speech_log(limit: int = 50, since_id: int = 0) -> Dict[str, Any]:
		_check_auth()
		entries = ctx.speech_log.get_entries(limit=limit, since_id=since_id)
		dicts = [e.to_dict() for e in entries]
		return {
			"entries": dicts,
			"count": len(dicts),
			"since_id": since_id,
		}

	reg.register(ToolDef(
		name="get_speech_log",
		description=(
			"Return recent utterances spoken by NVDA (mirrors the built-in "
			"Speech Viewer). Optional `since_id` returns only entries newer "
			"than that id, enabling incremental polling. Result is an object "
			"`{entries: Entry[], count: int, since_id: int}` where each "
			"Entry is `{id: int, timestamp: float, text: str}`."
		),
		handler=get_speech_log,
		input_schema={
			"type": "object",
			"properties": {
				"limit":    {"type": "integer", "default": 50},
				"since_id": {"type": "integer", "default": 0},
			},
			"additionalProperties": False,
		},
	))

	def get_last_spoken() -> Dict[str, Any]:
		_check_auth()
		entry: Optional[SpeechEntry] = ctx.speech_log.last_entry()
		return {"entry": entry.to_dict() if entry else None}

	reg.register(ToolDef(
		name="get_last_spoken",
		description=(
			"Return the most recent utterance NVDA spoke, wrapped as "
			"`{entry: Entry | null}` where Entry is "
			"`{id: int, timestamp: float, text: str}`. `entry` is null "
			"if NVDA has not spoken anything since the log was cleared."
		),
		handler=get_last_spoken,
		input_schema={"type": "object", "properties": {}, "additionalProperties": False},
	))

	def clear_speech_log() -> Dict[str, Any]:
		_check_auth()
		ctx.speech_log.clear()
		return {"ok": True}

	reg.register(ToolDef(
		name="clear_speech_log",
		description="Clear the in-memory speech log.",
		handler=clear_speech_log,
		input_schema={"type": "object", "properties": {}, "additionalProperties": False},
	))

	# --- Keyboard tools -----------------------------------------------------

	def send_key(gesture: str) -> Dict[str, Any]:
		_check_auth()
		try:
			ctx.keyboard.send_key(gesture)
		except InputError as exc:
			raise ValueError(str(exc)) from exc
		return {"ok": True, "gesture": gesture}

	reg.register(ToolDef(
		name="send_key",
		description=(
			"Simulate a single key or chord using NVDA gesture syntax: "
			"'a', 'enter', 'downArrow', 'control+shift+end', 'NVDA+f', "
			"'windows+d'."
		),
		handler=send_key,
		input_schema={
			"type": "object",
			"properties": {"gesture": {"type": "string"}},
			"required": ["gesture"],
			"additionalProperties": False,
		},
	))

	def send_keys(gestures: List[str], delay_ms: int = 0) -> Dict[str, Any]:
		_check_auth()
		try:
			n = ctx.keyboard.send_keys(gestures, delay_ms=delay_ms)
		except InputError as exc:
			raise ValueError(str(exc)) from exc
		return {"ok": True, "sent": n}

	reg.register(ToolDef(
		name="send_keys",
		description=(
			"Simulate a sequence of key gestures. Each item follows the same "
			"syntax as `send_key`. Optional `delay_ms` between keys."
		),
		handler=send_keys,
		input_schema={
			"type": "object",
			"properties": {
				"gestures": {"type": "array", "items": {"type": "string"}},
				"delay_ms": {"type": "integer", "default": 0},
			},
			"required": ["gestures"],
			"additionalProperties": False,
		},
	))

	def type_text(text: str, delay_ms: int = 0) -> Dict[str, Any]:
		_check_auth()
		try:
			n = ctx.keyboard.type_text(text, delay_ms=delay_ms)
		except InputError as exc:
			raise ValueError(str(exc)) from exc
		return {"ok": True, "sent": n, "requested": len(text)}

	reg.register(ToolDef(
		name="type_text",
		description=(
			"Type an arbitrary string by injecting per-character key gestures. "
			"Newline becomes Enter, tab becomes Tab. Characters that cannot be "
			"mapped on the current keyboard layout are skipped."
		),
		handler=type_text,
		input_schema={
			"type": "object",
			"properties": {
				"text":     {"type": "string"},
				"delay_ms": {"type": "integer", "default": 0},
			},
			"required": ["text"],
			"additionalProperties": False,
		},
	))

	# --- Introspection ------------------------------------------------------

	def get_focus_info() -> Dict[str, Any]:
		_check_auth()
		return run_on_main_thread(_collect_focus_info)

	reg.register(ToolDef(
		name="get_focus_info",
		description=(
			"Return a compact description of NVDA's current focus object: "
			"role, name, value, description, states, window title."
		),
		handler=get_focus_info,
		input_schema={"type": "object", "properties": {}, "additionalProperties": False},
	))

	def get_server_info() -> Dict[str, Any]:
		_check_auth()
		return {
			"name": config.MCP_SERVER_NAME,
			"version": config.MCP_SERVER_VERSION,
			"host": config.MCP_HOST,
			"port": config.MCP_PORT,
			"path": config.MCP_PATH,
			"auth_enabled": config.ENABLE_AUTH,
			"input_backends": [b.name for b in ctx.inputs.all()],
		}

	reg.register(ToolDef(
		name="get_server_info",
		description="Return metadata about this MCP server.",
		handler=get_server_info,
		input_schema={"type": "object", "properties": {}, "additionalProperties": False},
	))

	return reg


def _collect_focus_info() -> Dict[str, Any]:
	"""Runs on NVDA's main thread. Reads current focus and returns a dict."""
	try:
		import api  # type: ignore
		import controlTypes  # type: ignore
	except Exception as exc:  # noqa: BLE001
		return {"error": f"NVDA API unavailable: {exc}"}

	obj = api.getFocusObject()
	if obj is None:
		return {}

	def _safe(getter: Any) -> Any:
		try:
			return getter()
		except Exception:  # noqa: BLE001
			return None

	role = _safe(lambda: obj.role)
	role_name = None
	try:
		if role is not None:
			role_name = controlTypes.Role(role).name  # type: ignore[attr-defined]
	except Exception:  # noqa: BLE001
		role_name = str(role) if role is not None else None

	states = _safe(lambda: obj.states) or set()
	state_names: List[str] = []
	for st in states:
		try:
			state_names.append(controlTypes.State(st).name)  # type: ignore[attr-defined]
		except Exception:  # noqa: BLE001
			state_names.append(str(st))

	return {
		"name": _safe(lambda: obj.name) or "",
		"value": _safe(lambda: obj.value) or "",
		"description": _safe(lambda: obj.description) or "",
		"role": role_name,
		"states": sorted(state_names),
		"windowClassName": _safe(lambda: obj.windowClassName) or "",
		"windowText": _safe(lambda: obj.windowText) or "",
		"appModule": _safe(lambda: obj.appModule.appName if obj.appModule else None),
	}


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------

# Protocol version we advertise in ``initialize``. MCP clients negotiate
# by echoing back either what they support or a compatible fallback.
MCP_PROTOCOL_VERSION = "2025-03-26"


class Dispatcher:
	"""Handles a single JSON-RPC 2.0 request payload."""

	def __init__(self, tools: ToolRegistry) -> None:
		self._tools = tools

	def dispatch(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
		"""
		Return a JSON-RPC response dict or ``None`` for notifications
		(requests without ``id``).
		"""
		req_id = req.get("id")
		method = req.get("method")
		params = req.get("params") or {}

		# Notifications carry no id and expect no response.
		is_notification = "id" not in req

		try:
			if method == "initialize":
				result = self._handle_initialize(params)
			elif method == "ping":
				result = {}
			elif method == "tools/list":
				result = {"tools": self._tools.as_list()}
			elif method == "tools/call":
				result = self._handle_tools_call(params)
			elif method == "prompts/list":
				result = self._handle_prompts_list()
			elif method == "prompts/get":
				result = self._handle_prompts_get(params)
			elif method == "resources/list":
				result = self._handle_resources_list()
			elif method == "resources/read":
				result = self._handle_resources_read(params)
			elif method and method.startswith("notifications/"):
				# We accept and drop these silently.
				return None
			else:
				if is_notification:
					return None
				return self._error(
					req_id, JSONRPC_METHOD_NOT_FOUND,
					f"Method not found: {method!r}",
				)
		except _JsonRpcError as exc:
			if is_notification:
				return None
			return self._error(req_id, exc.code, exc.message, exc.data)
		except Exception as exc:  # noqa: BLE001
			log.exception("nvda-mcp: unhandled error in %s", method)
			if is_notification:
				return None
			return self._error(req_id, JSONRPC_INTERNAL_ERROR, repr(exc))

		if is_notification:
			return None
		return {"jsonrpc": "2.0", "id": req_id, "result": result}

	# --- Method handlers -------------------------------------------------

	def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
		# We just advertise ourselves; the client is free to pick any
		# protocol version it supports. We advertise all three
		# resource-carrying MCP surfaces (tools, prompts, resources)
		# so agent clients like Claude Desktop / Cline can discover
		# the full API without any out-of-band configuration.
		client_version = params.get("protocolVersion") or MCP_PROTOCOL_VERSION
		return {
			"protocolVersion": client_version,
			"capabilities": {
				"tools":     {"listChanged": False},
				"prompts":   {"listChanged": False},
				"resources": {"listChanged": False, "subscribe": False},
			},
			"serverInfo": {
				"name": config.MCP_SERVER_NAME,
				"version": config.MCP_SERVER_VERSION,
			},
		}

	def _handle_prompts_list(self) -> Dict[str, Any]:
		"""Return the list of prompt templates (without their message bodies)."""
		summaries: List[Dict[str, Any]] = []
		for p in PROMPTS:
			summaries.append({
				"name": p["name"],
				"title": p.get("title", p["name"]),
				"description": p["description"],
				"arguments": p.get("arguments", []),
			})
		return {"prompts": summaries}

	def _handle_prompts_get(self, params: Dict[str, Any]) -> Dict[str, Any]:
		"""Return the full message body of one prompt template."""
		name = params.get("name")
		if not isinstance(name, str):
			raise _JsonRpcError(JSONRPC_INVALID_PARAMS, "Missing prompt 'name'")
		for p in PROMPTS:
			if p["name"] == name:
				return {
					"description": p["description"],
					"messages": p["messages"],
				}
		raise _JsonRpcError(JSONRPC_METHOD_NOT_FOUND, f"Unknown prompt: {name!r}")

	def _handle_resources_list(self) -> Dict[str, Any]:
		"""Return the list of read-only reference resources."""
		summaries: List[Dict[str, Any]] = []
		for r in RESOURCES:
			summaries.append({
				"uri": r["uri"],
				"name": r["name"],
				"description": r["description"],
				"mimeType": r.get("mimeType", "text/plain"),
			})
		return {"resources": summaries}

	def _handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
		"""Return the content of one reference resource by URI."""
		uri = params.get("uri")
		if not isinstance(uri, str):
			raise _JsonRpcError(JSONRPC_INVALID_PARAMS, "Missing resource 'uri'")
		for r in RESOURCES:
			if r["uri"] == uri:
				return {
					"contents": [{
						"uri": r["uri"],
						"mimeType": r.get("mimeType", "text/plain"),
						"text": r["_text"],
					}],
				}
		raise _JsonRpcError(JSONRPC_METHOD_NOT_FOUND, f"Unknown resource: {uri!r}")

	def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
		name = params.get("name")
		if not isinstance(name, str):
			raise _JsonRpcError(JSONRPC_INVALID_PARAMS, "Missing tool 'name'")
		arguments = params.get("arguments") or {}
		if not isinstance(arguments, dict):
			raise _JsonRpcError(JSONRPC_INVALID_PARAMS, "'arguments' must be an object")

		tool = self._tools.get(name)
		if tool is None:
			raise _JsonRpcError(JSONRPC_METHOD_NOT_FOUND, f"Unknown tool: {name!r}")

		# Bind the tool's positional/keyword signature against arguments.
		sig = inspect.signature(tool.handler)
		try:
			bound_args = self._bind_kwargs(sig, arguments)
		except TypeError as exc:
			raise _JsonRpcError(JSONRPC_INVALID_PARAMS, str(exc)) from exc

		try:
			value = tool.handler(**bound_args)
		except PermissionError as exc:
			return _error_tool_result(f"Unauthorised: {exc}")
		except ValueError as exc:
			return _error_tool_result(str(exc))
		except Exception as exc:  # noqa: BLE001
			log.exception("nvda-mcp: tool %r failed", name)
			return _error_tool_result(f"Internal error: {exc!r}")

		return _success_tool_result(value)

	# --- Helpers ---------------------------------------------------------

	def _bind_kwargs(self, sig: inspect.Signature, args: Dict[str, Any]) -> Dict[str, Any]:
		"""Filter ``args`` to keys that the handler accepts."""
		params = sig.parameters
		return {k: v for k, v in args.items() if k in params}

	def _error(
		self,
		req_id: Any,
		code: int,
		message: str,
		data: Any = None,
	) -> Dict[str, Any]:
		err: Dict[str, Any] = {"code": code, "message": message}
		if data is not None:
			err["data"] = data
		return {"jsonrpc": "2.0", "id": req_id, "error": err}


class _JsonRpcError(Exception):
	def __init__(self, code: int, message: str, data: Any = None) -> None:
		super().__init__(message)
		self.code = code
		self.message = message
		self.data = data


def _success_tool_result(value: Any) -> Dict[str, Any]:
	"""
	Wrap a Python value into an MCP CallToolResult payload.

	Per the MCP spec, ``structuredContent`` must be a JSON object.
	All of our tools already return dicts, but this function
	defensively wraps non-dict values in ``{"result": value}`` so
	that a future tool author cannot accidentally break spec
	compliance and trip the reference client's pydantic
	validation (which is strict about this).
	"""
	text = json.dumps(value, ensure_ascii=False, default=str)
	if isinstance(value, dict):
		structured: Dict[str, Any] = value
	else:
		structured = {"result": value}
	return {
		"content": [{"type": "text", "text": text}],
		"structuredContent": structured,
		"isError": False,
	}


def _error_tool_result(message: str) -> Dict[str, Any]:
	return {
		"content": [{"type": "text", "text": message}],
		"isError": True,
	}


# ---------------------------------------------------------------------------
# HTTP server plumbing
# ---------------------------------------------------------------------------

def _make_handler(
	dispatcher: Dispatcher,
	mcp_path: str,
	ctx: "ServerContext",
	started_at: float,
) -> type:
	"""
	Return an ``HTTPRequestHandler`` subclass bound to ``dispatcher``.

	Using a factory (instead of module-level class) lets us capture the
	dispatcher without resorting to global state, which matters because
	tests may want to instantiate multiple servers.
	"""

	class _Handler(BaseHTTPRequestHandler):
		# Silence the default access log; we route stuff through our
		# own logger instead.
		def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
			log.debug("nvda-mcp http: " + fmt, *args)

		# GET /health         ->  {"status":"ok"}
		# GET /debug/status   ->  diagnostic snapshot (listener_attached, log_size, ...)
		# GET /<mcp>          ->  405 with an informative body
		# GET anything else   ->  404
		def do_GET(self) -> None:  # noqa: N802
			path = self.path.rstrip("/")
			if path == "/health":
				self._send_json(HTTPStatus.OK, {"status": "ok"})
				return
			if path == "/debug/status":
				self._send_json(HTTPStatus.OK, self._debug_status())
				return
			if path == mcp_path.rstrip("/"):
				self._send_json(
					HTTPStatus.METHOD_NOT_ALLOWED,
					{"error": "Use POST with JSON-RPC 2.0 payload"},
				)
				return
			self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

		def _debug_status(self) -> Dict[str, Any]:
			speech_log = ctx.speech_log
			# Try to get NVDA-side ground truth about the pre_speech
			# registrations. This tells us whether our module-level
			# handler is actually in NVDA's _handlers dict.
			try:
				nvda_diag = type(speech_log).diagnostics()
			except Exception as exc:  # noqa: BLE001
				nvda_diag = {"diagnostics_error": repr(exc)}
			return {
				"server": {
					"name": config.MCP_SERVER_NAME,
					"version": config.MCP_SERVER_VERSION,
					"uptime_seconds": round(time.time() - started_at, 2),
					"endpoint": f"http://{config.MCP_HOST}:{config.MCP_PORT}{config.MCP_PATH}",
				},
				"speech_log": {
					"self_id": id(speech_log),
					"listener_attached": getattr(speech_log, "is_attached", False),
					"is_active_receiver": getattr(speech_log, "is_active_receiver", False),
					"pre_speech_call_count": getattr(speech_log, "pre_speech_call_count", 0),
					"buffered_entries": len(speech_log),
					"next_id": getattr(speech_log, "_next_id", None),
				},
				"nvda_extension_points": nvda_diag,
				"input_backends": [b.name for b in ctx.inputs.all()],
				"auth_enabled": config.ENABLE_AUTH,
			}

		def do_POST(self) -> None:  # noqa: N802
			if self.path.rstrip("/") != mcp_path.rstrip("/"):
				self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
				return
			try:
				length = int(self.headers.get("Content-Length", "0") or "0")
			except ValueError:
				length = 0
			raw = self.rfile.read(length) if length > 0 else b""
			try:
				payload = json.loads(raw.decode("utf-8")) if raw else {}
			except Exception:  # noqa: BLE001
				self._send_json(
					HTTPStatus.BAD_REQUEST,
					{
						"jsonrpc": "2.0",
						"id": None,
						"error": {"code": JSONRPC_PARSE_ERROR, "message": "Invalid JSON"},
					},
				)
				return

			# JSON-RPC supports batching (array of requests). We handle both.
			if isinstance(payload, list):
				responses: List[Dict[str, Any]] = []
				for req in payload:
					if not isinstance(req, dict):
						continue
					resp = dispatcher.dispatch(req)
					if resp is not None:
						responses.append(resp)
				if not responses:
					# All notifications; respond 204.
					self.send_response(HTTPStatus.NO_CONTENT)
					self.end_headers()
					return
				self._send_json(HTTPStatus.OK, responses)
				return

			if not isinstance(payload, dict):
				self._send_json(
					HTTPStatus.BAD_REQUEST,
					{
						"jsonrpc": "2.0",
						"id": None,
						"error": {"code": JSONRPC_INVALID_REQUEST, "message": "Request must be an object or array"},
					},
				)
				return

			resp = dispatcher.dispatch(payload)
			if resp is None:
				# Notification; per JSON-RPC 2.0 we return 204.
				self.send_response(HTTPStatus.NO_CONTENT)
				self.end_headers()
				return
			self._send_json(HTTPStatus.OK, resp)

		# --- Utilities -------------------------------------------------

		def _send_json(self, status: HTTPStatus, body: Any) -> None:
			data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
			self.send_response(int(status))
			self.send_header("Content-Type", "application/json; charset=utf-8")
			self.send_header("Content-Length", str(len(data)))
			# Permissive CORS - useful when a browser-based MCP client tests
			# the endpoint. Localhost-only binding limits the risk.
			self.send_header("Access-Control-Allow-Origin", "*")
			self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
			self.end_headers()
			try:
				self.wfile.write(data)
			except BrokenPipeError:
				pass

		def do_OPTIONS(self) -> None:  # noqa: N802
			# Preflight for browser MCP clients.
			self.send_response(HTTPStatus.NO_CONTENT)
			self.send_header("Access-Control-Allow-Origin", "*")
			self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
			self.end_headers()

	return _Handler


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

class McpServerThread:
	"""
	Runs the HTTP MCP server on a dedicated daemon thread.

	Public API:
	  * :meth:`start`      – begin serving (idempotent)
	  * :meth:`stop`       – graceful shutdown, joins the thread
	  * :meth:`is_running` – True if the thread is alive
	"""

	def __init__(self, ctx: ServerContext) -> None:
		self._ctx = ctx
		self._tools = _build_tools(ctx)
		self._dispatcher = Dispatcher(self._tools)
		self._httpd: Optional[ThreadingHTTPServer] = None
		self._thread: Optional[threading.Thread] = None

	# --- Lifecycle ----------------------------------------------------------

	def is_running(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	def start(self) -> None:
		if self.is_running():
			return
		started_at = time.time()
		handler_cls = _make_handler(
			self._dispatcher, config.MCP_PATH, self._ctx, started_at,
		)
		try:
			self._httpd = ThreadingHTTPServer(
				(config.MCP_HOST, config.MCP_PORT), handler_cls,
			)
		except OSError as exc:
			log.exception(
				"nvda-mcp: could not bind %s:%s - %s",
				config.MCP_HOST, config.MCP_PORT, exc,
			)
			raise
		self._httpd.daemon_threads = True

		log.info(
			"nvda-mcp: HTTP MCP server listening at http://%s:%s%s "
			"(diagnostics: http://%s:%s/debug/status)",
			config.MCP_HOST, config.MCP_PORT, config.MCP_PATH,
			config.MCP_HOST, config.MCP_PORT,
		)

		self._thread = threading.Thread(
			target=self._httpd.serve_forever,
			name="nvda-mcp-server",
			daemon=True,
		)
		self._thread.start()

	def stop(self, timeout: float = 5.0) -> None:
		httpd = self._httpd
		if httpd is not None:
			try:
				httpd.shutdown()
			except Exception:  # noqa: BLE001
				pass
			try:
				httpd.server_close()
			except Exception:  # noqa: BLE001
				pass
		if self._thread is not None:
			self._thread.join(timeout=timeout)
		self._thread = None
		self._httpd = None
		log.info("nvda-mcp: server stopped")


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def build_default_context() -> ServerContext:
	"""Build the default :class:`ServerContext` used by the global plugin."""
	speech_log = SpeechLog()
	inputs = build_default_registry()
	auth = build_default_auth()
	return ServerContext(speech_log=speech_log, inputs=inputs, auth=auth)