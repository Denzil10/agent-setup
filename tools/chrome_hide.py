"""Hide a headed Chrome window for real, without the caller managing timing.

A --window-position off-screen coordinate is not a reliable way to keep a
window invisible: on a multi-monitor setup the combined desktop can extend
past the "off-screen" coordinate, landing the window on a second display's
visible area instead (found 2026-08-30 in two ChatGPT
scripts -- both used --window-position=4000,4000
and the window was still visible).

The real mechanism is a macOS App hide (same as Cmd+H), via System Events,
targeted by PID so it can never touch the user's own Chrome. The one wrinkle
is timing: the window doesn't exist yet the instant subprocess.Popen()
returns, so a single hide call right after spawning can silently no-op. This
module owns that retry so callers don't have to duplicate it.

Usage:
    proc = subprocess.Popen([CHROME_BIN, ...])
    hide_when_headed(proc.pid, headless)
    # go on to wait_for_cdp / connect_over_cdp -- no second call needed.
"""
from __future__ import annotations

import subprocess
import threading
import time


def _hide_once(pid: int) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to '
             f'set visible of (first process whose unix id is {pid}) to false'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def hide_when_headed(pid: int, headless: bool, retries: int = 6, interval: float = 1.5) -> None:
    """Hide the Chrome process at `pid`, retrying in the background.

    No-op if `headless` is true (nothing to hide). Otherwise fires immediately
    -- cheap and harmless even before the window exists -- then keeps retrying
    every `interval` seconds for up to `retries` attempts on a daemon thread,
    covering however long Chrome takes to actually create its window. Returns
    immediately; does not block Chrome startup or CDP connection.
    """
    if headless:
        return

    def _run() -> None:
        for _ in range(retries):
            _hide_once(pid)
            time.sleep(interval)

    threading.Thread(target=_run, daemon=True).start()
