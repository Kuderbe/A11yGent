# NVDA Coach — Tutorial Notes for MCP Agent Guide

Source: **NVDA Coach — Interactive Screen Reader Training v1.5.4** by Tony
Gebhard (installed as NVDA add-on). Launched via **NVDA menu → Help → NVDA
Coach**, or globally with **NVDA+Shift+C**.

Cross-referenced with `nvda/user_docs/en/userGuide.md` (upstream authoritative
key bindings, especially for object navigation and review cursor).

Purpose: raw notes taken while walking the tutorial through the `nvda` MCP
bridge. Everything **new** to the agent or **hard** for the agent is captured
here, then compressed into `_RESOURCE_AGENT_GUIDE` (v2) in `mcp_server.py`.

---

## 0. Discovery / launching the tutorial

- **NVDA Coach lives under NVDA menu → Help → NVDA Coach** (last item of the
  Help submenu). The Help submenu of NVDA 2026.1.1 has 11 items:
  1. User Guide (u), 2. Commands Quick Reference (q), 3. What's new (**n**),
  4. NV Access web site (w), 5. Help, training and support (h), 6. NV Access
  shop (s), 7. License (i), 8. Welcome dialog... (l), 9. Check for update...
  (c), 10. About... (a), 11. **NVDA Coach (n)**.
- **Mnemonic collision**: two Help submenu entries share the accelerator
  letter `n` ("What's new" and "NVDA Coach"). Pressing `n` in the open Help
  submenu therefore cycles between the two rather than activating either.
  **Do not rely on single-letter mnemonics in NVDA submenus** — arrow-key +
  Enter is the reliable path.
- **Add-on store is the ground truth for what's installed.**
  `NVDA+n → t → a` (NVDA menu → Tools → Add-on store) enumerates installed
  add-ons. NVDA Coach installs no top-level menu entry of its own — it only
  binds the global gesture `NVDA+Shift+C` and the Help submenu entry. **Not
  every add-on advertises itself in a menu.** The Add-on store is the only
  reliable inventory.
- **Global launcher shortcut**: `NVDA+Shift+C` opens the lesson picker from
  anywhere in the OS. Add-ons frequently bind their own `NVDA+…` shortcut
  without adding a menu; the Input Gestures dialog (Preferences → Input
  gestures, or `NVDA+n → p → n`) is the definitive list.

## 1. `get_focus_info` reads full text of read-only edit controls

**Biggest single time-saver of this session.** When the focused control is a
`role: EDITABLETEXT` with the `READONLY` and `MULTILINE` states — which is
what NVDA Coach uses for its lesson panels, and also what many Windows "About"
dialogs, help boxes, "release notes" widgets, log viewers, and email preview
panes use — `get_focus_info` returns the **entire text content** of the
control in both the `value` and `windowText` fields, cleanly formatted with
`\r\n` line breaks.

Consequences for the agent:

- **No need to read line by line with `downArrow` and reassemble utterances.**
  One `get_focus_info` call returns the whole document as a single string.
- **Rule**: after every focus change, call `get_focus_info` first. If `value`
  is non-empty AND `MULTILINE` + `READONLY` are in `states`, the content is
  right there. Skip the poll loop entirely.
- **Does NOT apply** to Chromium browse-mode documents
  (`role: DOCUMENT`, `windowClassName: Chrome_RenderWidgetHostHWND`) — those
  return empty `value` and still require the speech-log perception loop.

**During an active NVDA Coach lesson**, focus stays on the outer `wxWindowNR`
pane (`role: PANE`) — `get_focus_info` returns empty `value` there. The
lesson instruction is only in the speech log. Between lessons, on the "lesson
complete" and "welcome to NVDA Coach" screens, focus IS in the edit control,
so `get_focus_info` gives the full text. The heuristic:
`role=EDITABLETEXT AND READONLY IN states` → content in `value`.

## 2. The three-layer keyboard command model

Section 2 Lesson 1 ("Understanding Command Categories") makes an explicit
distinction the current agent-guide only implies. Every keystroke belongs to
exactly one of three layers:

1. **Windows / OS layer** — `Ctrl+X/C/V`, `Alt+Tab`, `Alt+F4`, `Win+…`,
   arrow keys inside a control, `Tab`/`Shift+Tab`, `Enter`, `Space`,
   `Escape`, `Home`/`End`, `PageUp`/`PageDown`. Work in every program.
   Injected via `keybd_event` on the Windows side of the bridge.
2. **Application layer** — `Ctrl+N` in Word (new document), `Ctrl+L` in Edge
   (focus address bar), `F5` in a browser (refresh), `Ctrl+Alt+Arrow` on a
   web table (which is actually implemented by NVDA but *acts on the
   application*). Also injected as OS keystrokes; the app decides how to
   handle them.
3. **NVDA / screen-reader layer** — `NVDA+T`, `NVDA+N`, `NVDA+F7`, all quick
   nav letters in Browse Mode, all object-navigation commands, `NVDA+Shift+D`
   (audio ducking), `NVDA+1` (Input Help). **These commands take NO action
   in the application — they only inform NVDA and produce speech.** They
   must reach NVDA's `inputCore` script layer, NOT the OS keyboard stack.

The bridge's dispatch routing in `input_bridge.KeyboardBackend.send_key`
implements this distinction: gestures with a bound NVDA script go through
`inputCore.manager.executeGesture(kig)` (layer 3), everything else through
`kig.send()` (layers 1 and 2). This model is not just an implementation
detail; **it's how a screen-reader user thinks about keys.** The agent-guide
should teach it explicitly.

## 3. **Desktop layout vs. Laptop layout** — critical, was missing from v1

NVDA has TWO keyboard-layout modes, chosen in Preferences → Settings →
Keyboard → "Keyboard layout" combo box (Desktop or Laptop). This is
**independent of physical hardware** — it's a software mapping.

- **Desktop layout** binds many NVDA commands to the numeric keypad
  (`NVDA+numpad4/5/6/7/8/9/2/3/1/Minus/…`).
- **Laptop layout** binds the same commands to `NVDA+letter` or
  `NVDA+shift+letter` combinations for keyboards without a numpad.

**If a gesture "does nothing" and it uses `numpad*`, the most likely cause
is that NVDA is set to laptop layout and the numpad binding is unbound.**
Vice versa for laptop combos on desktop layout.

For the agent, this means:

- **Every command that differs between layouts must be documented with BOTH
  key sequences** in the guide (as NVDA Coach itself does).
- **The bridge should be able to report the currently active layout** so
  the agent can pick the right variant. (New endpoint idea:
  `get_server_info` could return `kbdLayout: "desktop" | "laptop"`.)
- Common commands that DIFFER between layouts:
  * Read current line: `NVDA+upArrow` (**both** — same on both layouts)
  * Say-all: `NVDA+downArrow` (desktop) / `NVDA+A` (laptop)
  * Report current navigator object: `NVDA+numpad5` (desktop) /
    `NVDA+shift+O` (laptop)
  * Move to containing object (parent): `NVDA+numpad8` (desktop) /
    `NVDA+shift+upArrow` (laptop)
  * Move to previous object: `NVDA+numpad4` (desktop) /
    `NVDA+shift+leftArrow` (laptop)
  * Move to next object: `NVDA+numpad6` (desktop) /
    `NVDA+shift+rightArrow` (laptop)
  * Move to first contained object (first child): `NVDA+numpad2` (desktop) /
    `NVDA+shift+downArrow` (laptop)
  * Navigator to focus (sync navigator ← focus):
    `NVDA+numpadMinus` (desktop) / `NVDA+backspace` (laptop)
  * Focus to navigator (sync focus ← navigator):
    `NVDA+shift+numpadMinus` (desktop) / `NVDA+shift+backspace` (laptop) —
    press twice to also move the caret to the review position.
  * Switch review mode: `NVDA+numpad7`/`NVDA+numpad1` (desktop) /
    `NVDA+pageUp`/`NVDA+pageDown` (laptop)

Commands that are the SAME on both layouts (important — these always work):

- `NVDA+n` (menu), `NVDA+t` (title), `NVDA+tab` (describe focus),
  `NVDA+f7` (Elements List), `NVDA+f12` (time/date), `NVDA+b` (read whole
  window), `NVDA+end` (status bar), `NVDA+f` (formatting), `NVDA+k` (link
  URL), `NVDA+space` (toggle Browse/Focus), `NVDA+1` (Input Help), all
  Browse-Mode single-letter quick nav (h/d/k/f/e/b/1..6/…), Ctrl+Alt+Arrow
  table cell navigation, NVDA+control+f (Find), NVDA+Shift+C (NVDA Coach).

## 4. **Object navigation** — the big gap in v1

Object navigation was completely missing from `_RESOURCE_AGENT_GUIDE` v1.
This is the fallback for reaching controls that:

- Tab and Shift+Tab can't get to (Windows Tab-order gaps),
- Browse-Mode quick-nav can't get to (custom widgets without proper ARIA
  roles — the exact Gerstäcker sort-dropdown scenario from the previous
  session),
- system focus can never reach because they don't accept keyboard focus at
  all (screen-only labels, decorative icons, split-panel dividers).

**Mental model**: NVDA treats the screen as a *tree of objects*. The
application window is the root, panels/toolbars/menus are the next level,
individual controls (buttons, text fields, checkboxes) are the leaves.
Every accessibility element the OS exposes — via UI Automation, MSAA, or
IAccessible2 — is a node.

The **navigator object** is a separate cursor from system focus. Moving the
navigator does not change what's focused, does not click anything, does not
change the app's state — it's a read-only exploration cursor for the tree.

The full set of object-navigation commands (from
`nvda/user_docs/en/userGuide.md` §"Object Navigation"):

| Command                               | Desktop            | Laptop                |
|---------------------------------------|--------------------|-----------------------|
| Report current navigator object       | `NVDA+numpad5`     | `NVDA+shift+o`        |
| Move to containing object (parent)    | `NVDA+numpad8`     | `NVDA+shift+upArrow`  |
| Move to previous object (sibling)     | `NVDA+numpad4`     | `NVDA+shift+leftArrow` |
| Move to next object (sibling)         | `NVDA+numpad6`     | `NVDA+shift+rightArrow` |
| Move to first contained object (child)| `NVDA+numpad2`     | `NVDA+shift+downArrow` |
| Move to previous in flat view         | `NVDA+numpad9`     | `NVDA+shift+[`        |
| Move to next in flat view             | `NVDA+numpad3`     | `NVDA+shift+]`        |
| Sync navigator ← focus                | `NVDA+numpadMinus` | `NVDA+backspace`      |
| Sync focus ← navigator (once)         | `NVDA+shift+numpadMinus` | `NVDA+shift+backspace` |
| … press twice: also move caret        | (as above 2×)      | (as above 2×)         |
| Switch to next review mode            | `NVDA+numpad7`     | `NVDA+pageUp`         |
| Switch to previous review mode        | `NVDA+numpad1`     | `NVDA+pageDown`       |
| Report review cursor location         | `NVDA+shift+numpadDelete` | `NVDA+shift+delete` |

**Report** speaks name/role/state. **Press twice quickly** to spell the
name. **Press three times** to copy the name+value to the clipboard —
useful for extracting a value the agent needs to reason about but hasn't
seen in the speech log yet.

**Canonical recipe for custom-widget interaction (fixes Gerstäcker
sort-dropdown)**:

```
1. Tab / quick-nav to land near the widget (or click a nearby element).
2. NVDA+numpadMinus (or NVDA+backspace)     # sync navigator to focus
3. NVDA+numpad5 (or NVDA+shift+o)           # confirm role of current object
4. NVDA+numpad2 (or NVDA+shift+downArrow)   # descend into children
   NVDA+numpad6/4 (or NVDA+shift+left/right) # walk siblings
   NVDA+numpad5 at each stop                # confirm what we're on
5. When navigator lands on the target option:
   NVDA+shift+numpadMinus (or NVDA+shift+backspace)   # move focus to navigator
6. Enter / Space to activate.
```

## 5. Table navigation (was missing from v1)

**`Ctrl+Alt+Arrow` for cell-by-cell navigation** in HTML/Word/etc. tables.
Same on both layouts. NVDA announces cell content plus row/column position.

| Direction         | Gesture             |
|-------------------|---------------------|
| Next cell in row  | `control+alt+rightArrow` |
| Prev cell in row  | `control+alt+leftArrow`  |
| Cell below (col)  | `control+alt+downArrow`  |
| Cell above (col)  | `control+alt+upArrow`    |

Essential for scraping structured data (schedules, price tables, etc.)
without falling back to `NVDA+downArrow` say-all, which reads a table row
as a flat sentence and loses the column boundaries.

## 6. Text-reading commands (Section 4 of the tutorial)

Mostly Windows-native, but the agent should know these are the "read one
X" building blocks a screen-reader user relies on:

| Unit           | Move backward           | Move forward             | Read current            |
|----------------|-------------------------|--------------------------|-------------------------|
| Character      | `leftArrow`             | `rightArrow`             | (NVDA speaks on landing) |
| Word           | `control+leftArrow`     | `control+rightArrow`     | `NVDA+control+.` (numpad5×2 on desktop) — spell |
| Line           | `upArrow`               | `downArrow`              | `NVDA+upArrow` (**same on both layouts**) |
| Paragraph      | `control+upArrow`       | `control+downArrow`      | — |
| Page / screen  | `pageUp`                | `pageDown`               | — |
| Document       | `control+home`          | `control+end`            | — |
| Whole doc from cursor | —                | Say-all: `NVDA+downArrow` (desktop) / `NVDA+A` (laptop) | — |

Formatting at cursor: `NVDA+f` (same on both layouts). Selection announce:
`NVDA+shift+upArrow` (desktop) — reports current selection.

## 7. Browse-mode notes I missed in v1

- `NVDA+f7` (Elements List) is a **filterable table of contents** for the
  page. Inside the dialog:
  - `Tab` between the filter radio buttons: `Alt+H` (Links), `Alt+L`
    (Headings), `Alt+F` (Form fields), `Alt+B` (Buttons).
  - Then the type-ahead edit field filters by substring.
  - Arrow keys walk the filtered tree, `Enter` jumps to the target.
- `NVDA+control+f` opens NVDA's Find dialog **only when focus is in a
  browse-mode virtual buffer**. In a system focus context (edit field, form
  control), `Ctrl+F` reaches the app instead (browser Find bar in Edge).
  This is the source of the "Ctrl+F sometimes lands in Edge" bug from the
  previous session — it's an intentional NVDA behavior, not a bridge bug.
  Workaround: press `Escape` first to leave Focus Mode, or use `NVDA+f7`
  which works anywhere.

## 8. NVDA-Coach-specific meta-observations

- Interactive lessons have three step types:
  1. **Informational** — Enter advances to the next step. F3 skips.
  2. **Practice** — waits for the specific practiced key. Enter advances
     without penalty; F3 skips.
  3. **External practice window** — spawns a subprocess (login form,
     table demo, or a browser tab with a practice HTML). `Alt+Tab` to it,
     experiment, then `NVDA+Shift+C` to return.
- **Function-key convention in NVDA Coach**:
  * `F1` repeats the current instruction (useful when perception loop
    missed the utterance).
  * `F2` gives a hint (press repeatedly for progressively more).
  * `F3` skips the current step. In an agent workflow that only wants to
    *read* the lesson content without performing it, spamming F3 through
    each step captures every instruction in the speech log while forcing
    the lesson forward.
- `Ctrl+N` = next lesson, `Ctrl+B` = previous lesson, `Ctrl+R` = restart
  lesson. `Escape 3×` closes NVDA Coach entirely.
- The lesson-complete screen has focus in a read-only multi-line edit —
  `get_focus_info` returns the whole completion message. This is a good
  place to verify a lesson finished cleanly.

## 9. Input Help mode (`NVDA+1`) — self-documenting keystrokes

Toggled by `NVDA+1` (top-row 1, not numpad). While active, every keystroke
speaks what it *would* do without actually executing. Press `NVDA+1` again
to exit.

For an agent this is not directly useful (we can't consume speech
proactively), but it's the analog of the bridge's future planned tool
"what would `gesture X` do here?" — a static-analysis query against the
NVDA script layer. Worth noting because the bridge could later wrap this
into a `describe_gesture` MCP tool.

## 10. Self-report gestures — additions to the existing v1 list

- `NVDA+shift+B` — battery level and charging state.
- `NVDA+tab` — describe current focus (name + role + state). This is the
  keyboard equivalent of `get_focus_info` and shows up as speech-log entries
  like `"Username: edit focused blank"` / `"Password: edit protected blank"`
  / `"Remember me on this computer check box focused not checked"` — the
  `protected` state on a password field, in particular, is a piece of
  metadata I hadn't seen surfaced before.
- `NVDA+shift+D` — cycle audio ducking modes (not useful for the agent
  since the agent doesn't produce non-NVDA audio, but good to know it
  exists so it isn't mistaken for another function).

## 11. Escape ergonomics

- **Ctrl** stops NVDA speaking immediately. **Shift** pauses and, on second
  press, resumes. For an agent both are moot (we read the log, not the
  audio), but Ctrl is *also* the "cancel" of last resort in many NVDA
  contexts (e.g., during a long say-all). Sending a bare `Ctrl` keystroke
  as a defensive interrupt is a valid recovery move — but note the bridge
  routes `Ctrl` alone as an OS keystroke; whether it actually reaches
  NVDA's speech-cancel handler depends on injection reaching the low-level
  hook while NVDA is speaking. Best practice: use a targeted gesture
  rather than relying on Ctrl to interrupt a stuck utterance stream.
- **Escape three times** closes NVDA Coach. In general, `Escape` in NVDA
  contexts (dialogs, sub-menus, Focus Mode auto-triggered by a form field)
  is the universal "back out" key.

## 12. NVDA Coach chapter summary (for the agent guide)

| # | Chapter                             | Coverage                              |
|---|-------------------------------------|---------------------------------------|
| 1 | Introduction / About NVDA Coach     | Meta (Ctrl to stop, F1/F2/F3, NVDA+1) |
| 2 | Getting Started with NVDA (14)      | NVDA key, `NVDA+N/T/F12/Shift+B`, Tab/Shift+Tab, Enter/Space, `NVDA+UpArrow`, `NVDA+1`, User Guide, Ctrl stop, Alt+Tab |
| 3 | Your Keyboard (3)                   | Modifier locations, Fn key, **Desktop vs Laptop layout** |
| 4 | Reading and Moving Through Text (8) | Character/word/line/paragraph/page navigation, Home/End, **Say-All (NVDA+DownArrow / NVDA+A)**, select, Ctrl+C, `NVDA+F` for formatting |
| 5 | Browse Mode and Web Navigation (10) | Browse mode, H/heading levels, K link, F/E/B forms, Focus vs Browse mode, `NVDA+F7`, `NVDA+control+F`, D/L landmarks/lists, **`Ctrl+Alt+Arrow` table cells** |
| 6 | Object Navigation (6)               | **The full navigator-object command set** (see §4 above) |
| 7 | Customizing NVDA (4)                | Change keyboard layout, synth settings ring (`NVDA+control+arrows`), audio output device, `NVDA+Shift+D` audio ducking |
| 8 | Additional Training and Help        | External links only (HTML page in Edge) |

## 13. Things I got wrong in the previous session that this tutorial clarified

- I called the "Ctrl+F lands in the browser" behavior a **bridge bug**.
  It's not — it's NVDA's Find script being bound only to browse-mode
  virtual buffers by design. When focus is inside a form/edit, that key
  chord passes through to the app. Solution is: exit Focus Mode first
  (`Escape`) OR use `NVDA+F7` (Elements List) which works everywhere.
- I dismissed the custom Gerstäcker sort-dropdown as an "unresolvable
  accessibility barrier". It is a **real barrier for pure Browse-Mode
  navigation**, but Object Navigation would very likely have reached the
  options. A screen-reader native would have used `NVDA+numpadMinus` (sync
  navigator to focus), descended with `NVDA+numpad2`, walked siblings with
  `NVDA+numpad6`, and pressed `NVDA+shift+numpadMinus` on the target
  option to move focus there and hit Enter. That's a testable next step
  for the next real-world run.
- I underestimated `NVDA+F7`. It's not just an "elements list"; the four
  filter radios (Alt+H/L/F/B) and the substring type-ahead make it a
  first-class page search tool, especially for custom widgets that don't
  expose a proper ARIA role but DO have a name.