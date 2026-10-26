"""Close automation Chrome instances that no process is using any more.

browser.py deliberately leaves the persistent-profile Chrome running when its
Python process exits, so the next caller can attach. Its idle timer lives in
that process, so once the process is gone nothing ever closes the browser.
Chrome's own update relaunch does the same thing: it restarts the automation
instance under launchd with a new PID that no session file knows about.

An orphan like that is harmful beyond memory use. The automation Chrome shares
the bundle id com.google.Chrome with the user's own Chrome, and LaunchServices
hands Dock clicks, Spotlight launches and link opens to the older of the two.
Once the user's Chrome restarts, the orphan is older, and all of those land in
an off-screen window (2026-09-23: a 27h orphan on port 9300 swallowed them).

Run periodically by launchd. An instance is closed
only after it has had no CDP client for IDLE_TIMEOUT seconds and the fleet
browser lock is free. A handover session keeps its Python process connected
while the human acts, so it is never idle by this measure.

The same run also kills orphaned Playwright scripts that spin. When a sync
Playwright script loses its dispatcher greenlet, the wait loop in
playwright/_impl/_sync_base.py switches into a dead fiber, returns at once and
loops at 100% of a core. If the Claude shell that launched it is gone, nothing
notices (2026-10-11: a browser.py heredoc spun for 25h after its Bash task
failed). It also holds its CDP connection, so the Chrome check above never
fires for it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

AGENTS_TMP = Path.home() / ".agents/tmp"
STATE_FILE = AGENTS_TMP / "chrome-reaper.json"
SPIN_STATE_FILE = AGENTS_TMP / "chrome-reaper-spin.json"
# Share of one core an orphaned Playwright script must hold between two runs.
# A working script waits on the driver socket and stays near zero.
SPIN_CPU_SHARE = 0.8
SPIN_MIN_WINDOW = 60
FLEET_LOCK_DIR = AGENTS_TMP / "fleet-browser.lock"
IDLE_TIMEOUT = int(os.environ.get("CLAUDE_BROWSER_IDLE_TIMEOUT", "300"))
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def automation_chromes() -> dict[int, int]:
    """{pid: debug port} for main Chrome processes whose profile is under ~/.agents/tmp."""
    out = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True).stdout
    found = {}
    for line in out.splitlines():
        pid_s, _, cmd = line.strip().partition(" ")
        if not cmd.startswith(CHROME_BIN + " ") or "--type=" in cmd:
            continue
        dir_m = re.search(r"--user-data-dir=(\S+)", cmd)
        port_m = re.search(r"--remote-debugging-port=(\d+)", cmd)
        if not (dir_m and port_m and dir_m.group(1).startswith(str(AGENTS_TMP))):
            continue
        # A handover window is on screen for a human, who may still be using it
        # after the launching script has exited (replicate/yt.py does exactly
        # that). Every other mode is a candidate: headless, and hidden, whose
        # pages sit minimized in the Dock (2026-10-11: one instance kept 4 there
        # for 18h). Same test as browser.py's _live_mode.
        if "--window-position=100,100" in cmd:
            continue
        found[int(pid_s)] = int(port_m.group(1))
    return found


def has_client(pid: int, port: int) -> bool:
    """True if any process other than Chrome holds a connection to its debug port."""
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-Fp"],
        capture_output=True, text=True,
    ).stdout
    return any(line[1:] != str(pid) for line in out.splitlines() if line.startswith("p"))


def fleet_lock_held() -> bool:
    try:
        holder = int((FLEET_LOCK_DIR / "pid").read_text().strip())
        os.kill(holder, 0)
        return True
    except (OSError, ValueError):
        return False


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_gone(pid: int, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.5)
    return not alive(pid)


def close_chrome(pid: int, port: int) -> str:
    """CDP Browser.close, then SIGTERM, then SIGKILL. Returns the step that worked."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=10000)
            browser.new_browser_cdp_session().send("Browser.close")
    except Exception as exc:  # the browser dropping the socket mid-call is expected
        log(f"pid {pid}: Browser.close raised {type(exc).__name__}")
    if wait_gone(pid, 15):
        return "Browser.close"
    os.kill(pid, signal.SIGTERM)
    if wait_gone(pid, 15):
        return "SIGTERM"
    # Cookies are committed to disk every ~30s, so this loses at most that window.
    os.kill(pid, signal.SIGKILL)
    wait_gone(pid, 5)
    return "SIGKILL"


def cpu_seconds(field: str) -> float:
    """ps TIME ([[dd-]hh:]mm:ss.ss) in seconds."""
    days, _, rest = field.rpartition("-")
    total = 0.0
    for part in rest.split(":"):
        total = total * 60 + float(part)
    return total + int(days or 0) * 86400


def orphan_playwright_scripts() -> dict[int, float]:
    """{pid: cpu seconds} for launchd-parented processes driving a Playwright node driver.

    A script started by launchd itself also has PPID 1; it is only killed if it spins.
    """
    out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,time=,command="], capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        pid_s, ppid_s, time_s, cmd = (line.split(None, 3) + [""])[:4]
        rows[int(pid_s)] = (int(ppid_s), time_s, cmd)
    found = {}
    for ppid, _, cmd in rows.values():
        if "playwright/driver" not in cmd or "run-driver" not in cmd or ppid not in rows:
            continue
        gp, time_s, _ = rows[ppid]
        if gp == 1 and ppid != os.getpid():
            found[ppid] = cpu_seconds(time_s)
    return found


def reap_spinners(now: float) -> None:
    try:
        prev = {int(k): v for k, v in json.loads(SPIN_STATE_FILE.read_text()).items()}
    except (OSError, ValueError):
        prev = {}
    current = orphan_playwright_scripts()
    next_state = {}
    for pid, cpu in current.items():
        last_cpu, last_seen = prev.get(pid, (cpu, now))
        # A manual run right after the scheduled one would judge a few seconds of work.
        if now - last_seen < SPIN_MIN_WINDOW:
            next_state[pid] = [last_cpu, last_seen]
            continue
        share = (cpu - last_cpu) / (now - last_seen)
        if share >= SPIN_CPU_SHARE:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            log(f"killed orphaned Playwright script pid {pid}: {share:.0%} of a core for {int(now - last_seen)}s")
        else:
            next_state[pid] = [cpu, now]
    SPIN_STATE_FILE.write_text(json.dumps({str(k): v for k, v in next_state.items()}))


def main() -> None:
    try:
        state = {int(k): v for k, v in json.loads(STATE_FILE.read_text()).items()}
    except (OSError, ValueError):
        state = {}
    now = time.time()
    chromes = automation_chromes()
    busy = fleet_lock_held()
    next_state = {}
    for pid, port in chromes.items():
        if busy or has_client(pid, port):
            next_state[pid] = now
            continue
        # First sighting counts as activity, so a just-launched browser gets a full window.
        last = state.get(pid, now)
        idle = now - last
        if idle < IDLE_TIMEOUT:
            next_state[pid] = last
            continue
        step = close_chrome(pid, port)
        log(f"closed automation Chrome pid {pid} port {port}, idle {int(idle)}s, via {step}")
    STATE_FILE.write_text(json.dumps({str(k): v for k, v in next_state.items()}))
    reap_spinners(now)


if __name__ == "__main__":
    main()
