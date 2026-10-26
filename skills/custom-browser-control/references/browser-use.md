# Browser Automation with browser-use CLI

The `browser-use` command provides fast, persistent browser automation. A background daemon keeps the browser open across commands, giving ~50ms latency per call.

## Prerequisites

```bash
browser-use doctor    # Verify installation
```

For setup details, see https://github.com/browser-use/browser-use/blob/main/browser_use/skill_cli/README.md

## Core Workflow

1. **Navigate**: `browser-use open <url>` — starts browser if needed
2. **Inspect**: `browser-use state` — returns clickable elements with indices
3. **Interact**: use indices from state (`browser-use click 5`, `browser-use input 3 "text"`)
4. **Verify**: `browser-use state` or `browser-use screenshot` to confirm
5. **Repeat**: browser stays open between commands
6. **Cleanup**: `browser-use close` when done

## Local HTML Files

For local HTML, prefer serving the containing directory and opening the page over `http://127.0.0.1:<port>/...`.
In this environment, direct `file://` navigation can produce a blank/empty DOM in `browser-use state` even when the URL changes.

```bash
python3 -m http.server 8765 --bind 127.0.0.1
browser-use open http://127.0.0.1:8765/system.html
browser-use state
```

## Browser Modes

```bash
browser-use open <url>                         # Default: headless Chromium
browser-use --headed open <url>                # Visible window
browser-use --profile \"Default\" open <url>      # Real Chrome with Default profile (existing logins/cookies)
browser-use --profile \"Profile 1\" open <url>   # Real Chrome with named profile
browser-use --connect open <url>               # Auto-discover running Chrome via CDP
browser-use --cdp-url ws://localhost:9222/... open <url>  # Connect via CDP URL
```

`--connect`, `--cdp-url`, and `--profile` are mutually exclusive.

## Commands

```bash
# Navigation
browser-use open <url>                    # Navigate to URL
browser-use back                          # Go back in history
browser-use scroll down                   # Scroll down (--amount N for pixels)
browser-use scroll up                     # Scroll up
browser-use switch <tab>                  # Switch to tab by index
browser-use close-tab [tab]              # Close tab by index (default: current)
```

## Form Interaction

```bash
browser-use input <index> \"text\"        # Type text into input by index
browser-use select <index> <value>        # Select dropdown option by index and value
browser-use check <index>                 # Check checkbox by index
browser-use uncheck <index>               # Uncheck checkbox by index
browser-use radio <index>                 # Select radio button by index
browser-use file <index> <path>           # Upload file by index and path
```

## Actions

```bash
browser-use click <index>                 # Click element by index
browser-use doubleclick <index>           # Double-click element by index
browser-use rightclick <index>            # Right-click element by index
browser-use hover <index>                 # Hover over element by index
browser-use drag <from_index> <to_index>  # Drag element from one index to another
```

## Extraction

```bash
browser-use extract <index>               # Extract text from element by index
browser-use extract-all <selector>        # Extract text from all elements matching selector
browser-use extract-attr <index> <attr>   # Extract attribute value by index and attribute name
browser-use screenshot [path]             # Screenshot of current page (optional path)
browser-use pdf [path]                    # PDF of current page (optional path)
```

## State & Info

```bash
browser-use state                         # Get current state: URL, title, elements
browser-use title                         # Get page title
browser-use url                           # Get current URL
browser-use html                          # Get page HTML
browser-use text                          # Get page visible text
browser-use cookies                       # Get cookies
browser-use local-storage                 # Get local storage
browser-use session-storage               # Get session storage
```

## Debugging

```bash
browser-use logs                          # Get browser console logs
browser-use network                       # Get network request logs
```

## Advanced

```bash
browser-use script <js>                   # Execute JavaScript in page context
browser-use wait <selector>               # Wait for element to appear
browser-use wait-hidden <selector>        # Wait for element to disappear
browser-use wait-timeout <ms>             # Wait for milliseconds
browser-use eval <js>                     # Evaluate JavaScript and return result
```