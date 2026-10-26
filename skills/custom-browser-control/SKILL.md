---
name: custom-browser-control
description: "Launch and control an isolated Chrome session through the local CDP/Playwright controller. Use for browser testing, form filling, data extraction, screenshots, and persistent sessions in Personal projects."
triggers:
  - Need to control a browser via Python API
  - Need to automate browser interactions via command-line
  - Web scraping, testing, or form filling tasks
inputs: []
steps:
  - Determine whether low-level API (browser-control) or high-level CLI (browser-use) better fits the task.
  - For low-level API: use get_browser() to obtain a browser instance and interact via snapshot(), elements(), click(), type(), etc.
  - For high-level CLI: use the browser-use command suite (open, state, click, input, screenshot, etc.) for rapid iteration.
  - Always ensure proper cleanup: close browser instances or sessions when done.
  - Verify outcomes via DOM checks, screenshots, or expected network responses.
verification:
  - Browser launches and responds to commands.
  - Intended actions (clicks, inputs, navigations) produce expected DOM changes.
pitfalls:
  - Forgetting to close browsers can leave orphaned processes.
  - Headed automation shares the owner's GUI session: it can steal the keyboard and leave windows behind. See "Sharing the owner's desktop" below.
  - Using file:// URLs may yield empty DOM; serve local files via HTTP instead.
  - Mixed use of API and CLI may cause session conflicts; prefer one approach per session.
references:
  - references/browser-control.md   # Low-level Python API details
  - references/browser-use.md       # High-level CLI command reference
---
# Custom Browser Control

This skill provides two complementary approaches to browser automation:

1. **Low-level Python API** (see `references/browser-control.md`): Direct control via `get_browser()` for fine-grained scripting within Python agents.
2. **High-level CLI** (see `references/browser-use.md`): Persistent browser daemon with a rich command set for rapid interactive automation.

Choose the approach that matches your needs: use the Python API when you need programmatic control within an agent's code flow; use the CLI for quick iterative tasks, debugging, or when you prefer a shell-driven workflow.

Both approaches share the same underlying browser infrastructure (Chromium) and support features like persistent sessions, profile management, tunneling, and cloud browser integration.

See the referenced files for detailed usage, commands, and pitfalls specific to each approach.


## Sharing the owner's desktop

The automation Chrome runs in the owner's own macOS login session, so any
headed automation window ends up in front of them.

**Three modes (2026-10-01).**

| Mode | Call | Use for | On screen |
|---|---|---|---|
| headless | `get_browser(url)` (default) | everything that works headless | never |
| hidden | `headless=False` | a site that refuses headless | no: started with no window (`open -j -g`, `--no-startup-window`); pages open in a window created minimized via `Target.createTarget`; focus guard. Exception: a site `window.open` popup (OAuth) is drawn ~1s before it is minimized — run login flows as handover |
| handover | `handover=True` | an agent hands the owner a blocker it cannot clear (login, 2FA, CAPTCHA) | yes, at 100,100; never for captures |

Headless sends the desktop User-Agent: the `HeadlessChrome` token alone was
what Cloudflare walled on chatgpt.com, so ChatGPT callers now run headless.

Why "hidden" minimizes instead of positioning off-screen: macOS clamps a window
that is on no display onto the nearest one. With the owner's external monitor
left of the laptop, `--window-position=-10000,-10000` landed fully on it, and
Chrome un-hid itself on each new page (2026-09-28). A minimized window is in the
Dock whatever the app's hidden state.

Live-instance rules (one Chrome per profile): headless and hidden callers share
whichever of the two is live, except a hidden caller evicts a headless one. A
handover caller evicts any non-handover Chrome. Automation refuses a handover
window younger than `CLAUDE_BROWSER_HANDOVER_GRACE` (1800s) and evicts it after.

Verified 2026-10-01 by sampling CGWindowList every 50ms: headless and hidden showed
zero on-screen windows and never took the foreground while loading ChatGPT.
Never test window behaviour on the owner's live screen without their go-ahead.

**It leaks windows.** When `get_browser()` *attaches* to a long-lived Chrome it
does not own, `close()` used to tear down nothing at all, and an OAuth popup
arrives via `window.open` so it never passes through caller code either. Sign-in
windows therefore accumulated for days. Now: every page created after attach is
tracked, identity-host ones are closed on `close()`, and `fleet_browser_unlock`
calls `sweep_auth_popups()` at lock release to catch jobs that were killed and
never ran their own teardown.

Other pages a session opens stay open (`CLAUDE_BROWSER_CLOSE_NEW_PAGES=1` closes them), so a hidden
instance collects minimized windows in the Dock. `tools/chrome_reaper.py` (launchd, every 120s)
closes any headless or hidden instance with no CDP client for 5 minutes; handover is never reaped.

Two traps when writing any such cleanup:

- For a window Playwright did not create, `page.url` and `page.main_frame.url`
  stay `''` forever. Use `_page_url(page)`, which falls back to
  `evaluate("() => location.href")`. `page.on("framenavigated")` does not fire
  for these pages either.
- A Google popup on an already-signed-in profile does not stay on
  `accounts.google.com`; it lands on `myaccount.google.com`. Both are in
  `AUTH_POPUP_HOSTS`.

**Real isolation** would be a separate macOS user account for automation, so
the automation GUI session is not the owner's at all. That is the owner's call
to make, not something to set up unasked.
