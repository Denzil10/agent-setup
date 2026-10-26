# Browser Control

```python
from tools.browser import get_browser

with get_browser("https://example.com") as b:
    snap  = b.snapshot()           # ARIA tree ~700 tokens — full layout
    elems = b.elements()           # interactive elements only ~200 tokens
    text  = b.text()               # plain visible text ~50–300 tokens
    b.navigate("https://x.com")
    b.click("button[type=submit]")
    b.type("input[name=q]", "search term")
    b.press("input[name=q]", "Enter")
    b.wait_for(".results")
    img = b.screenshot()           # PNG bytes
    
    # Bypass Google Account Chooser and click the specified email account:
    b.select_google_account("you@example.com")
```

## Read strategy
1. `b.text()` — is the page loaded? what does it say?
2. `b.elements()` — what can I click/type?
3. `b.snapshot()` — need full layout or ARIA roles?

## Rules
- Always use a `with` block
- Session persists between `with` blocks — browser stays open until 5 min idle
- Always use the Chrome user data directory at `~/.agents/tmp/automation_user_data` and profile `Profile 1` (Automation).
- **Before any OAuth consent, login, or account-scoped action** (not just browsing): verify which Google account is actually active, don't assume. This profile can hold several saved Google accounts with near-identical names. Navigating to a page like `chrome://new-tab-page/` or `https://myaccount.google.com/` and reading the signed-in identity from the page text is a reliable check; don't infer the account from which one the automation *meant* to use. Incident (2026-08-30): an OAuth flow silently proceeded against a similarly named account that was already signed in, until a manual look at the account page caught it.
- `headless=False` alone does **not** produce a visible window — it still opens off-screen and hides the app (`background_headed` mode, meant for invisible automation). For any step that needs a human to see and interact with the browser (manual login, 2FA, passkeys, CAPTCHA), pass **both** `headless=False` and `handover=True` — only `handover=True` places the window on-screen at a normal position.
- **Default policy, applies even outside this tool** (e.g. a repo-specific script that launches Chrome directly with `subprocess.Popen` instead of `get_browser()`): headless unless a specific site is known to hard-block headless (e.g. Cloudflare on ChatGPT). If headed is required to get past that block, **hide the window for real — don't rely on an off-screen `--window-position`.** A coordinate guess like `4000,4000` is not reliably off-screen: on a multi-monitor setup the combined desktop can extend past it, landing the "hidden" window on a second display's visible area (this actually happened, 2026-08-30, in two ChatGPT scripts).
  Use the shared helper instead of reimplementing this per script — it owns the retry timing so the caller doesn't have to:
  ```python
  sys.path.insert(0, str(Path.home() / ".agents"))
  from tools.chrome_hide import hide_when_headed

  chrome_proc = subprocess.Popen([...])
  hide_when_headed(chrome_proc.pid, headless)   # one call, no-ops if headless
  ```
  `hide_when_headed` (in `~/.agents/tools/chrome_hide.py`) does a real macOS App hide via System Events, targeted by PID so it can never touch the user's own Chrome, and retries on a background thread for a few seconds to cover the gap between `Popen()` returning and the window actually existing — no second call after CDP connects needed. Keep `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, and `--disable-background-timer-throttling` regardless — Chromium throttles timers on any hidden/occluded window, and some automations poll for a React state update that throttling delays. Only go fully on-screen (`handover=True` in this tool, or a normal window position elsewhere) when a human genuinely needs to see and act on the page.
- **One Chrome per user-data-dir.** Chrome exits immediately if a second instance targets a directory another Chrome already owns, so `get_browser()` discovers the live instance from its `SingletonLock` PID plus that process's own `--remote-debugging-port` and attaches to it. Never launch Chrome yourself against `automation_user_data` while an agent session may be running, and never "fix" a busy profile by picking another port -- that is the failure that used to surface as `Chrome CDP port 93xx not ready after 15.0s`. If the profile is locked by a Chrome with no debug port, `get_browser()` now raises an error naming the PID to kill.
- **`handover=True` sessions don't idle out until the first `touch()`.** The 5-minute idle timer is suppressed while a human acts in the window; the first `touch()` afterwards re-arms it, so a visible Chrome does not outlive the script and hold the profile lock. Nothing calls `touch()` while your script blocks on `input()`, so the timer used to close Chrome mid-login and throw away the half-written session -- the reason ChatGPT logins did not stick. Normal sessions still idle out after `CLAUDE_BROWSER_IDLE_TIMEOUT` (default 300s).
- **Only the process that launched Chrome may close it.** A process that attached to an existing browser detaches on close instead of calling `browser.close()`, which over CDP would terminate the shared browser under whoever owns it.
- **`close_browser()` only kills a Chrome this process launched.** A process that merely attached gets a detach and a printed notice instead; `close_browser(force=True)` is the deliberate "kill the shared browser" call and belongs in an operator script, never in automation that shares the profile. Do not write your own lock-cleaning step (`pkill -f automation_user_data`, deleting `SingletonLock`, unlinking the session state file) -- `get_browser()` discovers and attaches to a live instance, so killing it just removes the profile from under whoever owns it.
- **Never launch Chrome yourself for a manual login.** Use `get_browser(url, headless=False, handover=True)`. Hand-writing `browser-session-cdp/active-session.json` no longer works: the handoff state file now lives inside the profile directory (`<profile>/.agent-cdp-session.json`) so it cannot drift away from the profile it describes.
- **Throwaway clones are garbage-collected.** A session that owns an ephemeral clone removes it via `atexit` on normal exit, and every `get_browser()` call sweeps `~/.agents/tmp/browser-session-cdp/agent-*` once per process, deleting clones whose creating PID is dead and whose directory no Chrome still holds. This exists because nine leaked clones (12 GB reclaimed, each a full copy of the real profile including `Cookies`) had built up from processes killed before `close()`.
- **Do not blank or delete `CLAUDE_BROWSER_STATIC_DIR`.** Empty/unset selects the throwaway-clone path: it clones the *real* Chrome profile into `~/.agents/tmp/browser-session-cdp/agent-<pid>-<ts>` and deletes it on close, so anything you log into there is discarded. If you want the persistent automation session, set it to `~/.agents/tmp/automation_user_data`.
- Headless mode reports the honest `HeadlessChrome/<real version>` user agent. The previous hard-coded `Chrome/122` spoof is gone -- it advertised a three-major-versions-stale headed browser from a Chrome 152 binary, which is worse than telling the truth. Sites that hard-block headless (ChatGPT/Cloudflare) still need headed-hidden, not a UA lie.
- `playwright-stealth` is applied when installed and prints a warning to stderr when it is not, so the same profile cannot silently present two different fingerprints depending on which venv ran it. `CLAUDE_BROWSER_STEALTH=0` opts out deliberately.
- For contenteditable inputs (e.g. Gemini): `b.page.click(sel)` then `b.page.keyboard.type(text)` — `b.type()` won't work
- `CLAUDE_BROWSER_IDLE_TIMEOUT=N` overrides idle timeout (seconds, default 300)
- If session closed mid-use, a `RuntimeError` is raised — just call `get_browser()` again
- Requires `PYTHONPATH=~/.agents` (set in global settings.json)
