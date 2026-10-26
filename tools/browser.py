"""
Browser automation helper. Clones Chrome Profile 1 into an isolated Chrome
user-data dir, launches real Chrome with CDP, and attaches Playwright to it.

This uses the same clone/launch approach that works in Studio, while preserving
the browser-control skill API:

    from tools.browser import get_browser

    with get_browser("https://example.com") as b:
        print(b.text())
        b.click("button[type=submit]")

The browser session is shared per process and closes after IDLE_TIMEOUT seconds
of inactivity (default 5 min, override with CLAUDE_BROWSER_IDLE_TIMEOUT). A
handover session (handover=True) never idles out -- a human is acting in that
window and no timer should close it mid-login.

Three modes:
  headless (default)   -- no window at all. Uses the desktop User-Agent, which
                          is enough for Cloudflare-fronted sites like ChatGPT.
  hidden (headless=False) -- a real headed Chrome for sites headless cannot
                          pass. Started with no window, pages opened in a
                          window created minimized, focus guard. A site's own
                          window.open popup is drawn ~1s before it is
                          minimized, so login flows belong in handover.
  handover (handover=True) -- a visible window an agent opens for the owner to
                          clear a blocker it cannot (login, 2FA, CAPTCHA).

One Chrome owns one user-data-dir; Chrome exits immediately if a second instance
targets the same directory. Every caller therefore discovers the live instance
from Chrome's own DevToolsActivePort/SingletonLock and attaches to it, rather
than picking a fresh port. Only the process that launched Chrome may close it.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page, sync_playwright

SOURCE_ROOT = Path.home() / "Library/Application Support/Google/Chrome"
SOURCE_PROFILE = os.environ.get("CLAUDE_BROWSER_PROFILE", "Profile 1")
SOURCE_PROFILE_DIR = SOURCE_ROOT / SOURCE_PROFILE
CLONE_ROOT = Path(os.environ.get("BROWSER_CLONE_ROOT", str(Path.home() / ".agents/tmp/browser-session-cdp")))
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_APP = "/Applications/Google Chrome.app"  # for macOS 'open -jg' launch
IDLE_TIMEOUT = int(os.environ.get("CLAUDE_BROWSER_IDLE_TIMEOUT", "300"))
# How long a handover window belongs to the owner before automation may evict it.
HANDOVER_GRACE = int(os.environ.get("CLAUDE_BROWSER_HANDOVER_GRACE", "1800"))
# A clone younger than this is never swept, however dead its creating PID looks.
CLONE_MIN_AGE = 3600

_CLONE_REMOVE = [
    "Singleton*",
    "RunningChromeVersion",
    "Crashpad",
    "ShaderCache",
    "GrShaderCache",
    "GraphiteDawnCache",
    "component_crx_cache",
    "extensions_crx_cache",
    "download_cache",
    "Safe Browsing",
    "CertificateRevocation",
    "optimization_guide_model_store",
    "Sessions",
    "Tabs",
    "Current Session",
    "Current Tabs",
    "Last Session",
    "Last Tabs",
]

_session: Optional["_BrowserSession"] = None
_lock = threading.Lock()
_SWEPT = False


@atexit.register
def _cleanup_ephemeral_session() -> None:
    """Tear down a throwaway clone on normal exit.

    Only for sessions that own their clone directory. A session on the shared
    persistent profile is deliberately left running so the next process can
    attach to it instead of paying for a cold Chrome start.
    """
    session = _session
    if session and not session._closed and session._owns_clone_dir:
        try:
            session.close()
        except Exception:
            pass

# Hosts whose windows are always a transient identity step, never a page a
# caller drives to completion. Used to sweep abandoned sign-in popups.
AUTH_POPUP_HOSTS = (
    "accounts.google.com",
    # Where an already-signed-in Google popup lands once the chooser resolves.
    "myaccount.google.com",
    "appleid.apple.com",
    "login.microsoftonline.com",
    "www.facebook.com/v", "www.facebook.com/dialog",
    "api.twitter.com/oauth", "x.com/i/oauth2",
    "github.com/login/oauth",
)


def _resolved_user_data_dir() -> Optional[Path]:
    """The persistent profile this process will use, or None for a throwaway clone."""
    static = os.environ.get(
        "CLAUDE_BROWSER_STATIC_DIR", str(Path.home() / ".agents/tmp/automation_user_data")
    )
    return Path(static) if static else None


def _state_file() -> Path:
    """Where the CDP port/PID handoff lives.

    Keyed to the *profile* rather than to BROWSER_CLONE_ROOT. The two are set by
    independent environment variables, so a caller that overrides only one used
    to look in a different place, conclude no session existed, and spawn a second
    Chrome against the same user-data-dir -- which Chrome refuses, exiting at once
    and leaving the new CDP port unopened ("port 93xx not ready").
    """
    profile_dir = _resolved_user_data_dir()
    if profile_dir:
        return profile_dir / ".agent-cdp-session.json"
    return CLONE_ROOT / "active-session.json"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cdp_reachable(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
        return True
    except Exception:
        return False


def _sweep_stale_clones() -> int:
    """Delete throwaway profile clones whose owning process is gone.

    An ephemeral clone is removed by close(), but close() never runs when the
    process is SIGKILLed or crashes -- and every clone is a full copy of the real
    Chrome profile, cookies included. Nine of them (19 GB) had accumulated before
    this existed. The directory name carries the creating PID, so a clone is
    collectable once that PID is dead and no Chrome still has the directory open.
    """
    removed = 0
    try:
        candidates = list(CLONE_ROOT.glob("agent-*"))
    except OSError:
        return 0
    for path in candidates:
        if not path.is_dir():
            continue
        try:
            _, pid_text, created_text = path.name.split("-", 2)
            pid, created = int(pid_text), int(created_text)
        except (IndexError, ValueError):
            continue
        if time.time() - created < CLONE_MIN_AGE:
            continue  # too young to judge; macOS recycles PIDs, so a fresh run
                      # whose Chrome has not spawned yet can look collectable
        if _pid_alive(pid):
            continue
        try:
            if subprocess.run(
                ["pgrep", "-f", f"user-data-dir={path}"], capture_output=True, text=True
            ).stdout.strip():
                continue  # a Chrome outlived its launcher; leave it alone
        except Exception:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


def _is_primary_chrome_dir(path: Path) -> bool:
    """True when the target is the user's own Chrome profile root, not an automation one."""
    try:
        return path.resolve() == SOURCE_ROOT.resolve()
    except OSError:
        return False


def _port_of_pid(pid: int) -> int | None:
    """Read --remote-debugging-port off a running Chrome's own command line."""
    try:
        out = subprocess.run(
            ["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True
        ).stdout
    except Exception:
        return None
    marker = "--remote-debugging-port="
    if marker not in out:
        return None
    tail = out.split(marker, 1)[1].split()[0].strip()
    return int(tail) if tail.isdigit() else None


def _discover_live_instance(user_data_dir: Path) -> dict | None:
    """Ask Chrome which port and PID own this profile.

    Both facts come from the running browser rather than from a file we wrote:
    the owning PID from the SingletonLock symlink Chrome maintains, and the debug
    port from that process's own command line. A state file written by one harness
    and read by another can drift; these cannot. Returns a dict with cdp_ok=False
    when the profile is locked by a Chrome that has no usable debug port; the
    caller must not try to launch a second instance in that case.

    DevToolsActivePort is checked only as a fallback: Chrome 152 on macOS does not
    write it when an explicit --remote-debugging-port is passed, which is how every
    session here is launched.
    """
    try:
        pid = int(os.readlink(user_data_dir / "SingletonLock").rsplit("-", 1)[1])
    except (OSError, ValueError, IndexError):
        return None
    if not _pid_alive(pid):
        return None  # stale lock; Chrome clears it on the next launch
    port = _port_of_pid(pid)
    if port is None:
        try:
            port = int((user_data_dir / "DevToolsActivePort").read_text().splitlines()[0].strip())
        except (OSError, ValueError, IndexError):
            port = None
    if port is not None and _cdp_reachable(port):
        return {"port": port, "pid": pid, "clone_dir": str(user_data_dir), "cdp_ok": True}
    return {"port": port, "pid": pid, "clone_dir": str(user_data_dir), "cdp_ok": False}


def _read_cdp_state() -> dict | None:
    """Return {port, pid, clone_dir} if an active CDP session exists."""
    profile_dir = _resolved_user_data_dir()
    if profile_dir and profile_dir.exists():
        found = _discover_live_instance(profile_dir)
        if found:
            return found
    try:
        import json as _json
        data = _json.loads(_state_file().read_text())
        port, pid = data["port"], data["pid"]
        if not _pid_alive(pid) or not _cdp_reachable(port):
            return None
        data["cdp_ok"] = True
        return data
    except Exception:
        return None


def _write_cdp_state(port: int, pid: int, clone_dir: str) -> None:
    import json as _json
    target = _state_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_json.dumps({"port": port, "pid": pid, "clone_dir": clone_dir}))


def _clear_cdp_state() -> None:
    try:
        _state_file().unlink()
    except FileNotFoundError:
        pass


def _live_mode(existing: dict) -> str | None:
    """'headless', 'hidden' or 'handover' for a live Chrome, read off its own command line."""
    try:
        cmd = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(existing["pid"])],
                             capture_output=True, text=True).stdout
    except Exception:
        return None
    if not cmd:
        return None
    if "--headless" in cmd:
        return "headless"
    return "handover" if "--window-position=100,100" in cmd else "hidden"


def _age_seconds(pid: int) -> int:
    try:
        etime = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)],
                               capture_output=True, text=True).stdout.strip()
        days, _, hms = etime.rpartition("-")
        parts = [int(x) for x in hms.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        return 0


def _desktop_user_agent() -> str:
    """The User-Agent headed Chrome sends, for use by a headless one.

    Headless Chrome announces "HeadlessChrome" in its UA header, and that token
    alone is what put chatgpt.com behind a never-resolving Cloudflare page:
    on 2026-09-28 the same profile, headless, got "Just a moment..." with the
    stock UA and the logged-in composer with this one. The version is read from the installed Chrome, reduced the way
    Chrome itself reduces it (major.0.0.0).
    """
    try:
        out = subprocess.run([CHROME_BIN, "--version"], capture_output=True, text=True, timeout=10).stdout
        major = out.split()[-1].split(".")[0]
    except Exception:
        major = "153"
    return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")


def _evict_mismatched(existing: dict) -> bool:
    """Kill a live Chrome whose mode this caller cannot use.

    get_browser() attaches to whatever Chrome already holds the profile, and
    attaching cannot change its mode. A headed caller on a headless Chrome was
    walled by Cloudflare: seven days of the ChatGPT review channel died that way
    (2026-09-08..15) behind an orphaned headless Chrome on port 9300. A handover
    caller needs a visible window, which no other mode has.

    This deliberately breaks the ownership rule stated on close_browser(): we
    kill a browser we did not launch. Scheduled callers hold fleet_browser_lock,
    so no other autopilot is mid-flight on the profile. A fresh handover window
    (the owner may be mid-login) is never evicted by automation; see get_browser().
    """
    pid = existing.get("pid")
    if not pid:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(40):  # up to ~4s for the port to actually free
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    _clear_cdp_state()
    print(f"[browser] evicted Chrome pid {pid}: its mode does not match this caller's",
          flush=True)
    return True


_STEALTH_WARNED = False


def _apply_stealth(page: Page) -> None:
    """Apply playwright-stealth, or say clearly that it is not installed.

    Whether stealth runs changes the page fingerprint, so a silent no-op made the
    same profile look like two different browsers depending on which venv the
    caller happened to use. Set CLAUDE_BROWSER_STEALTH=0 to opt out deliberately.
    """
    global _STEALTH_WARNED
    if os.environ.get("CLAUDE_BROWSER_STEALTH", "1") == "0":
        return
    try:
        try:
            from playwright_stealth import Stealth  # v2 API
            Stealth().apply_stealth_sync(page)
        except ImportError:
            from playwright_stealth import stealth_sync  # v1 API
            stealth_sync(page)
    except ImportError:
        if not _STEALTH_WARNED:
            _STEALTH_WARNED = True
            print(
                "tools.browser: playwright-stealth is not installed in this "
                "interpreter; the page fingerprint differs from venvs that have it. "
                "Install it, or set CLAUDE_BROWSER_STEALTH=0 to opt out.",
                file=__import__("sys").stderr,
            )
    except Exception as exc:
        if not _STEALTH_WARNED:
            _STEALTH_WARNED = True
            print(f"tools.browser: stealth failed to apply: {exc}", file=__import__("sys").stderr)


def _free_port(start: int = 9300) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free debug port in 9300-9400")


def _clone_profile(dest: Path) -> None:
    """Clone Chrome Profile 1 into a clean user-data dir."""
    if not SOURCE_PROFILE_DIR.exists():
        raise RuntimeError(f"Chrome profile not found: {SOURCE_PROFILE_DIR}")

    dest.mkdir(parents=True, exist_ok=True)
    for name in ("Local State", "First Run", "Last Version"):
        src = SOURCE_ROOT / name
        if src.exists():
            shutil.copy2(src, dest / name)

    profile_dest = dest / SOURCE_PROFILE
    if profile_dest.exists():
        shutil.rmtree(profile_dest)
    subprocess.run(["cp", "-Rc", str(SOURCE_PROFILE_DIR), str(profile_dest)], check=True, capture_output=True)

    for search_root in (dest, profile_dest):
        for pattern in _CLONE_REMOVE:
            for path in search_root.glob(pattern):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)


def _wait_for_cdp(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Chrome CDP port {port} not ready after {timeout}s")


def _find_chrome_pid(port: int) -> int | None:
    """Find the PID of the Chrome process listening on the given CDP port."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"remote-debugging-port={port}"],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _frontmost_pid() -> int | None:
    try:
        res = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get unix id of '
             'first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5,
        )
        out = res.stdout.strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def _hide_chrome_app(pid: int) -> None:
    """Hide only our Chrome process by PID (like Cmd+H); the owner's Chrome is a different pid."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to '
             f'set visible of (first process whose unix id is {pid}) to false'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _minimize_window(page: "Page") -> None:
    """Minimize the window holding this page.

    The hidden mode's real guarantee. An off-screen position does not work:
    macOS clamps a window that is on no display onto the nearest one, which on
    2026-09-28 was the owner's external monitor. An app hide does not hold:
    Chrome un-hides itself when a page opens a window. A minimized window is
    in the Dock, not on any screen, whatever the app's hidden state.
    """
    try:
        cdp = page.context.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": "minimized"}})
        cdp.detach()
    except Exception:
        pass


def _page_url(page: "Page") -> str:
    """Current URL of a page, including popups attached over CDP.

    `page.url` and `main_frame.url` both stay empty for a window Playwright did
    not itself create -- an OAuth popup arrives that way -- so fall back to
    asking the page. Verified: url == '' while location.href was the real
    myaccount.google.com the window had redirected to.
    """
    try:
        if page.url:
            return page.url
    except Exception:
        pass
    try:
        return page.evaluate("() => location.href") or ""
    except Exception:
        return ""


class _BrowserSession:
    def __init__(self):
        self.clone_dir: Optional[Path] = None
        self._owns_clone_dir = False
        # False when we attached to a Chrome another process launched. Closing
        # over CDP would kill that browser under its owner, so a non-owner
        # detaches instead.
        self._owns_chrome = True
        self._idle_disabled = False
        self.chrome_proc = None
        self.pw = None
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None
        self._closed = False
        self._idle_timer: Optional[threading.Timer] = None
        self._last_used = time.time()
        # Pages that appeared AFTER this session attached. An OAuth flow opens
        # its account chooser with window.open(), so the popup never passes
        # through any caller's code and nothing ever closes it: when we attached
        # to a long-lived Chrome we do not own, close() tore down nothing at all
        # and every abandoned sign-in window stayed on screen for days. Tracked
        # here so close() can shut them; pages that existed before we attached
        # belong to someone else and are never touched.
        self._opened_pages: list = []
        self._hidden = False
        self._chrome_pid: Optional[int] = None
        self._focus_guard: Optional[threading.Thread] = None
        self._focus_guard_stop: Optional[threading.Event] = None

    def start(self, url: str, headless: bool = True, window_size: str = "400,300", handover: bool = False) -> None:
        try:
            static_dir = os.environ.get("CLAUDE_BROWSER_STATIC_DIR", str(Path.home() / ".agents/tmp/automation_user_data"))
            if static_dir:
                self.clone_dir = Path(static_dir)
                self.clone_dir.mkdir(parents=True, exist_ok=True)
            else:
                self.clone_dir = CLONE_ROOT / f"agent-{os.getpid()}-{int(time.time())}"
                _clone_profile(self.clone_dir)
                self._owns_clone_dir = True

            locked = _discover_live_instance(self.clone_dir)
            if locked and locked["cdp_ok"]:
                # A usable Chrome already owns this profile -- possibly one no
                # state file describes, e.g. launched by hand or by an older
                # script. Attach to it. Launching here would exit immediately
                # (one instance per user-data-dir) and only reach this browser
                # through the slower failure path below.
                self.chrome_proc = None
                self._owns_chrome = False
                try:
                    self._connect(locked["port"], url)
                except Exception as exc:
                    # The port answers but the browser refuses to be driven --
                    # e.g. a long-lived Chrome whose default context was left
                    # unmanageable by an earlier client ("Browser context
                    # management is not supported"). Launching is not an option
                    # either, since it owns the profile, so name the fix.
                    raise RuntimeError(
                        f"Chrome PID {locked['pid']} owns {self.clone_dir} and answers on port "
                        f"{locked['port']}, but Playwright cannot drive it ({exc.__class__.__name__}: "
                        f"{str(exc).splitlines()[0]}). Restart it: kill {locked['pid']}"
                    ) from exc
                _write_cdp_state(locked["port"], locked["pid"], str(self.clone_dir))
                self._idle_disabled = handover
                self._reset_idle_timer()
                return
            if locked and not locked["cdp_ok"]:
                if _is_primary_chrome_dir(self.clone_dir):
                    raise RuntimeError(
                        f"{self.clone_dir} is your own Chrome's user-data-dir and Chrome is "
                        f"running (PID {locked['pid']}). Automating it would require closing "
                        f"your live browser, so this is refused. Point "
                        f"CLAUDE_BROWSER_STATIC_DIR at the automation profile "
                        f"(~/.agents/tmp/automation_user_data) instead."
                    )
                raise RuntimeError(
                    f"Chrome PID {locked['pid']} already owns {self.clone_dir} but exposes no "
                    f"usable debug port. Chrome refuses a second instance on one user-data-dir, "
                    f"so launching here would exit immediately. Close it first: "
                    f"kill {locked['pid']}"
                )
            port = _free_port()

            # Chrome flags common to all modes
            chrome_flags = [
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self.clone_dir}",
                f"--profile-directory={SOURCE_PROFILE}",
                "--no-first-run",
                "--no-default-browser-check",
            ]

            if headless:
                chrome_flags += [
                    "--headless=new",
                    "--window-size=1280,800",
                    f"--user-agent={_desktop_user_agent()}",
                ]
            elif handover:
                chrome_flags += ["--window-size=1280,800", "--window-position=100,100"]
            else:
                # Minimized windows count as occluded; without these Chrome
                # throttles their timers and rAF, which stalls SPA state updates.
                # No startup window: _connect() creates the first page in a
                # window that is born minimized, so nothing is ever drawn.
                chrome_flags += [
                    "--no-startup-window",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                ]

            hidden = not headless and not handover
            if not hidden:
                chrome_flags.append("about:blank")
            if hidden:
                # `open -j` launches the app hidden and `-g` keeps it out of the
                # foreground. `-n` forces a new instance beside the owner's Chrome.
                self.chrome_proc = subprocess.Popen(
                    ["open", "-n", "-j", "-g", "-a", CHROME_APP, "--args", *chrome_flags],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                self.chrome_proc = subprocess.Popen(
                    [CHROME_BIN, *chrome_flags],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            try:
                _wait_for_cdp(port)
            except RuntimeError:
                # Two processes that start together both see an unowned profile and
                # both pick the same free port; the loser's Chrome exits at once
                # because Chrome allows one instance per user-data-dir. Attach to
                # whoever won rather than failing the caller.
                winner = _discover_live_instance(self.clone_dir)
                if not (winner and winner["cdp_ok"]):
                    raise
                self.chrome_proc = None
                self._owns_chrome = False
                self._connect(winner["port"], url)
                self._idle_disabled = handover
                self._reset_idle_timer()
                return
            pid = self.chrome_proc.pid
            if hidden:
                pid = _find_chrome_pid(port) or pid
                self.chrome_proc._chrome_pid = pid  # close() kills this, not the `open` wrapper
                self._hidden = True
                self._chrome_pid = pid

            self._connect(port, url)
            if hidden:
                self._start_focus_guard(pid)

            _write_cdp_state(port, pid, str(self.clone_dir))
            # A handover session exists so a human can act in the window -- log in,
            # clear a 2FA prompt, solve a CAPTCHA. Nothing calls touch() while the
            # caller blocks on input(), so the idle timer used to close Chrome
            # mid-login after IDLE_TIMEOUT and discard the half-written session.
            self._idle_disabled = handover
            self._reset_idle_timer()
        except Exception:
            self.close()
            raise

    def attach(self, port: int, clone_dir_str: str, url: str, pid: int | None = None,
               handover: bool = False) -> None:
        """Re-attach to an already-running Chrome (cross-process reuse).

        Each attaching process gets its own CDP connection; the browser is
        shared. get_browser() has already made sure its mode matches ours.
        """
        try:
            self.clone_dir = Path(clone_dir_str)
            self.chrome_proc = None  # not ours to manage
            self._owns_chrome = False
            # Every attacher to a hidden Chrome keeps it hidden: windows that
            # appear while this process drives it are this process's to minimize.
            if pid is not None and _live_mode({"pid": pid}) == "hidden":
                self._hidden = True
                self._chrome_pid = pid
            self._connect(port, url)
            if self._hidden:
                self._start_focus_guard(pid)
            self._idle_disabled = handover
            self._reset_idle_timer()
        except Exception:
            self.close()
            raise

    def _connect(self, port: int, url: str) -> None:
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        time.sleep(0.3)

        # Chrome 149+ headless=new may report alive via /json/version but have
        # zero contexts/targets — trying to call any browser-level CDP method
        # (e.g. Browser.setDownloadBehavior) then raises:
        #   "Browser context management is not supported"
        # Detect this early and raise so the caller can spawn a fresh Chrome.
        if not self.browser.contexts:
            # Attempt to open a new context; if Chrome rejects it, surface clearly
            try:
                self.context = self.browser.new_context()
            except Exception as exc:
                raise RuntimeError(
                    f"CDP connected but browser has no contexts and new_context() failed "
                    f"(likely headless Chrome 149+ context-management restriction): {exc}"
                ) from exc
        else:
            self.context = self.browser.contexts[0]

        # Reuse existing page if any; open a new one otherwise
        pages = self.context.pages
        self.context.on("page", self._track_page)
        if pages:
            self.page = pages[0]
        elif self._hidden:
            self.page = self._new_minimized_page()
        else:
            self.page = self.context.new_page()
        if self._hidden:
            for page in self.context.pages:
                _minimize_window(page)
        _apply_stealth(self.page)
        if url and url != "about:blank":
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                # ERR_ABORTED can fire when reattaching to an already-loaded page;
                # try once more with a looser wait condition
                try:
                    self.page.goto(url, wait_until="commit", timeout=30_000)
                    time.sleep(1.5)
                except Exception:
                    pass  # page may already be on the right URL — caller can check

    def _new_minimized_page(self) -> "Page":
        """Open a page in a window that is created minimized and never drawn.

        context.new_page() opens a normal window that can only be minimized
        after it has been shown. Verified 2026-10-01 with on-screen sampling
        every 50ms: this path shows no window, never takes the foreground, and
        the page still reports visibilityState "visible" (ChatGPT loads).
        """
        cdp = self.browser.new_browser_cdp_session()
        with self.context.expect_page(timeout=15_000) as created:
            cdp.send("Target.createTarget", {
                "url": "about:blank", "newWindow": True, "windowState": "minimized",
                "background": True, "focus": False,
            })
        cdp.detach()
        return created.value

    def _track_page(self, page: "Page") -> None:
        # Fired for every page/popup created while we are attached, including
        # ones opened by the site itself rather than by the caller.
        self._opened_pages.append(page)
        if self._hidden:
            _minimize_window(page)
            if self._chrome_pid and _frontmost_pid() == self._chrome_pid:
                _hide_chrome_app(self._chrome_pid)

    def _start_focus_guard(self, pid: int) -> None:
        """Keep the hidden Chrome out of the foreground for the whole session.

        Minimizing hides the pixels, not the activation: Chrome takes the
        keyboard when a window is created (an OAuth popup does exactly that),
        and the owner cannot type. Poll the frontmost process and hide Chrome
        whenever it is frontmost. Only then -- hiding a non-frontmost app
        reshuffles the activation stack and bounced the owner into an
        unrelated app; and never re-activate a remembered app, which is stale.
        """
        if self._focus_guard:
            return
        self._focus_guard_stop = threading.Event()

        def _loop() -> None:
            while not self._focus_guard_stop.is_set():
                if _frontmost_pid() == pid:
                    _hide_chrome_app(pid)
                self._focus_guard_stop.wait(2.0)

        self._focus_guard = threading.Thread(target=_loop, daemon=True)
        self._focus_guard.start()

    def _stop_focus_guard(self) -> None:
        if self._focus_guard_stop:
            self._focus_guard_stop.set()
        self._focus_guard = None

    def close_auth_popups(self) -> int:
        """Close sign-in popups this session caused. Returns how many closed.

        Deliberately narrow: only pages that appeared after we attached AND
        now sitting on an identity-provider host. A working tab the caller is
        driving is never one of these -- it is `self.page`, which is skipped --
        so this is safe to run unconditionally.
        """
        closed = 0
        for page in list(self._opened_pages):
            try:
                if page.is_closed() or page is self.page:
                    continue
                url = _page_url(page)
                if any(h in url for h in AUTH_POPUP_HOSTS):
                    page.close()
                    closed += 1
            except Exception:
                pass
        return closed

    def close_opened_pages(self) -> int:
        """Close every page this session opened. Opt-in via CLAUDE_BROWSER_CLOSE_NEW_PAGES."""
        closed = 0
        for page in list(self._opened_pages):
            try:
                if page.is_closed() or page is self.page:
                    continue
                page.close()
                closed += 1
            except Exception:
                pass
        return closed

    def touch(self) -> None:
        self._last_used = time.time()
        # A handover session suppresses the idle timer while a human acts in the
        # window. The first touch afterwards means the script has control again and
        # the session cookie is already on disk, so re-arm -- otherwise the visible
        # Chrome outlives the script and holds the profile lock indefinitely.
        self._idle_disabled = False
        self._reset_idle_timer()

    def _reset_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self._idle_disabled:
            return
        self._idle_timer = threading.Timer(IDLE_TIMEOUT, self._on_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _on_idle(self) -> None:
        global _session
        with _lock:
            self.close()
            _session = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_focus_guard()
        if self._idle_timer:
            self._idle_timer.cancel()
        # Leaked sign-in popups outlive a non-owning session forever, so sweep
        # before detaching. Auth popups always; every opened page only when the
        # caller asked, since some callers leave a working tab behind on purpose.
        try:
            self.close_auth_popups()
            if os.environ.get("CLAUDE_BROWSER_CLOSE_NEW_PAGES") == "1":
                self.close_opened_pages()
        except Exception:
            pass
        # browser.close() over CDP terminates the whole browser, not just this
        # connection -- only the process that launched it may do that.
        shutdown = [getattr(self.browser, "close", None)] if self._owns_chrome else []
        for fn in shutdown + [getattr(self.pw, "stop", None)]:
            if fn:
                try:
                    fn()
                except Exception:
                    pass
        try:
            if self.chrome_proc:
                # When launched via 'open -jg', chrome_proc is the 'open' wrapper
                # which has already exited. The real Chrome PID is stashed separately.
                chrome_pid = getattr(self.chrome_proc, "_chrome_pid", None)
                if chrome_pid:
                    try:
                        os.kill(chrome_pid, 15)  # SIGTERM
                    except ProcessLookupError:
                        pass
                else:
                    self.chrome_proc.terminate()
                    self.chrome_proc.wait(timeout=10)
                _clear_cdp_state()
        except Exception:
            pass
        if self.clone_dir and self.chrome_proc and self._owns_clone_dir:
            # Remove only an ephemeral clone created for this session.
            shutil.rmtree(self.clone_dir, ignore_errors=True)


class BrowserWrapper:
    def __init__(self, session: "_BrowserSession"):
        self._s = session
        self.page: Page = session.page

    def _touch(self) -> None:
        if self._s._closed:
            raise RuntimeError("Browser session has been closed (idle timeout). Call get_browser() again.")
        self._s.touch()

    def navigate(self, url: str) -> None:
        self._touch()
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    def click(self, selector: str) -> None:
        self._touch()
        self.page.click(selector)

    def type(self, selector: str, text: str) -> None:
        self._touch()
        self.page.fill(selector, text)

    def press(self, selector: str, key: str) -> None:
        self._touch()
        self.page.press(selector, key)

    def wait_for(self, selector: str, timeout: int = 30_000) -> None:
        self._touch()
        self.page.wait_for_selector(selector, timeout=timeout)

    def snapshot(self) -> Any:
        """ARIA accessibility tree when available, with local fallbacks."""
        self._touch()
        body = self.page.locator("body")
        if hasattr(body, "aria_snapshot"):
            return body.aria_snapshot()
        try:
            return self.page.accessibility.snapshot()
        except Exception:
            return self.text()

    def elements(self) -> list:
        """Interactive elements only."""
        self._touch()
        return self.page.evaluate(
            """() => {
                return [...document.querySelectorAll(
                    'a,button,input,select,textarea,[role=button],[onclick]'
                )].map((el, i) => ({
                    i,
                    tag: el.tagName.toLowerCase(),
                    id: el.id || null,
                    name: el.getAttribute('name') || null,
                    type: el.getAttribute('type') || null,
                    text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 80),
                }));
            }"""
        )

    def text(self) -> str:
        """Visible page text."""
        self._touch()
        return self.page.evaluate("() => document.body?.innerText || ''")

    def screenshot(self) -> bytes:
        """Returns PNG bytes."""
        self._touch()
        return self.page.screenshot()

    def eval(self, js: str) -> Any:
        self._touch()
        return self.page.evaluate(js)

    def close_auth_popups(self) -> int:
        """Close abandoned sign-in popups this session caused."""
        return self._s.close_auth_popups()

    def select_google_account(self, email: str) -> bool:
        """Helper to bypass Google Account Chooser and click the given email account."""
        self._touch()
        import time

        _apply_stealth(self.page)
        time.sleep(2)
        
        if "Choose an account" in self.text() or "accountchooser" in self.page.url:
            print(f"Google Account Chooser detected. Selecting {email}...")
            
            link = self.page.locator("div[role='link']").filter(has_text=email).first
            if link.is_visible():
                link.focus()
                inner_text_div = link.locator("div.pGzURd").first
                if inner_text_div.is_visible():
                    inner_text_div.click()
                else:
                    link.click()
                print(f"Successfully selected account: {email}")
                time.sleep(5)
                return True
            else:
                print(f"Account card for '{email}' not found on the page.")
                return False
        return False




def sweep_auth_popups(port: int = 9300, timeout: float = 5.0) -> list[str]:
    """Close every identity-provider tab open on a live Chrome, over plain CDP HTTP.

    A session that is killed rather than closed (tick timeout, SIGKILL) never
    runs close(), so its sign-in popup survives. This needs no session and no
    Playwright attach, so it is safe to run from a janitor between jobs.
    Returns the URLs closed.
    """
    import json as _json

    def _get(path: str) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")

    closed: list[str] = []
    try:
        targets = _json.loads(_get("/json/list"))
    except Exception:
        return closed
    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url") or ""
        if not any(h in url for h in AUTH_POPUP_HOSTS):
            continue
        try:
            _get(f"/json/close/{t['id']}")
            closed.append(url)
        except Exception:
            pass
    return closed


def close_browser(force: bool = False) -> None:
    """Terminate the background Chrome this process launched.

    The browser is shared across every Python process on the profile, so a
    caller that merely attached to it must not kill it -- doing so pulls the
    profile out from under whatever automation actually owns it, and any login
    in flight there is lost. Without force=True this refuses that case and only
    drops the local connection. force=True is the deliberate "kill the shared
    browser" call; it belongs in an operator script, not in automation.
    """
    global _session
    with _lock:
        owns = bool(_session and _session._owns_chrome)
        existing = _read_cdp_state()
        if existing and (owns or force):
            try:
                os.kill(existing["pid"], signal.SIGTERM)
                print(f"Terminated background Chrome process with PID {existing['pid']}.")
            except Exception as e:
                print(f"Error terminating background process: {e}")
            _clear_cdp_state()
        elif existing:
            print(
                f"Chrome PID {existing['pid']} was launched by another process; "
                f"detaching instead of killing it (pass force=True to override)."
            )
        if _session:
            _session.close()
            _session = None

@contextlib.contextmanager
def get_browser(
    url: str = "about:blank",
    headless: bool = True,
    window_size: str = "400,300",
    handover: bool = False,
    close_session: bool = False,
    force_fresh: bool = False,
):
    """
    Context manager for browser automation.

    One Chrome window is shared across ALL Python processes:
    - If close_session=True, terminates the active background process immediately.
    - If force_fresh=True, kills any existing session and spawns a new one.
    - If an active-session.json exists and Chrome is still alive, re-attach.
      If re-attach fails (e.g. Chrome 149 headless context error), falls back
      to spawning a fresh Chrome automatically.
    - Otherwise spawn a fresh Chrome and write active-session.json.
    Session auto-closes after IDLE_TIMEOUT seconds of inactivity.
    """
    if close_session:
        close_browser()
        yield None
        return

    # A handover window exists to be seen. headless defaults to True, and
    # start() checks headless before handover, so handover=True alone used to
    # launch an invisible headless Chrome: three GitHub sign-in handovers on
    # 2026-10-04 timed out with no window on the owner's screen.
    if handover:
        headless = False
    mode = "handover" if handover else ("headless" if headless else "hidden")

    global _session, _SWEPT
    if not _SWEPT:
        _SWEPT = True
        _sweep_stale_clones()

    with _lock:
        if force_fresh:
            # Nuke existing session so we always get a clean Chrome
            if _session and not _session._closed:
                _session.close()
            _session = None
            _clear_cdp_state()

        if _session is None or _session._closed:
            existing = _read_cdp_state()
            # Attaching cannot change a live Chrome's mode. Headless and hidden
            # callers share whichever of those two is live -- except that a
            # hidden caller needs a real browser (see _evict_mismatched). A
            # handover caller needs its visible window. A live handover window
            # is the owner's for HANDOVER_GRACE seconds; automation refuses
            # it rather than drive or kill it mid-login, and evicts it after.
            if existing and existing.get("cdp_ok", True):
                live = _live_mode(existing)
                if live == "handover" and mode != "handover":
                    if _age_seconds(existing["pid"]) < HANDOVER_GRACE:
                        raise RuntimeError(
                            f"A handover Chrome (pid {existing['pid']}) is open for the owner on the "
                            f"automation profile; automation will not drive a visible window. "
                            f"Finish or close it, then rerun.")
                    mismatch = True
                else:
                    mismatch = (live == "headless" and mode == "hidden") or \
                               (live in ("headless", "hidden") and mode == "handover")
                if mismatch and _evict_mismatched(existing):
                    existing = None
            _session = _BrowserSession()
            if existing:
                try:
                    _session.attach(existing["port"], existing["clone_dir"], url,
                                     pid=existing.get("pid"), handover=handover)
                except Exception:
                    # Stale/broken Chrome (e.g. headless CDP context error) —
                    # clear the saved state and spawn a fresh instance.
                    _clear_cdp_state()
                    _session = _BrowserSession()
                    _session.start(url, headless=headless, window_size=window_size, handover=handover)
            else:
                _session.start(url, headless=headless, window_size=window_size, handover=handover)
        elif url and url != "about:blank":
            _session.touch()
            _session.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        else:
            _session.touch()
    try:
        yield BrowserWrapper(_session)
    finally:
        # The session can already be gone when the body raised mid-teardown
        # (a SIGALRM timeout in gemini_web_query, 2026-10-02); an
        # AttributeError here would replace the caller's real exception.
        if _session is not None:
            _session.touch()
