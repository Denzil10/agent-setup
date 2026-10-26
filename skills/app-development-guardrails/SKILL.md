---
name: app-development-guardrails
description: End-to-end guardrails for app development and debugging across mobile/frontend/backend workflows. Use when building, running, testing, or fixing apps where failures can come from runtime state, environment drift, flaky UI automation, API contract mismatch, or noisy logs. Trigger for Flutter/Android app runs, ADB-driven interaction tests, API integration debugging, and "works but not clicking"/"400 from endpoint" style issues.
---

# App Development Guardrails

## Overview
Apply a strict preflight-debug-verify workflow before concluding fixes. Prefer evidence from logs, focused runtime checks, and endpoint-level validation over assumptions.

## Workflow

### 1) Preflight runtime state
- Confirm process and target state before debugging behavior.
- For Android/Flutter: verify active ADB endpoint, lock state, and focused window before sending taps.
- Run `scripts/android_focus_preflight.sh <package>` to detect focus hijack (`com.android.systemui`, notification shade, lockscreen).
- If wireless debugging is used, reuse currently connected ADB endpoint first; treat mDNS ports as volatile.

### 2) Build and dependency integrity
- After changing third-party overrides or platform code, run clean rebuilds (`flutter clean`, `flutter pub get`, fresh run).
- Confirm dependency overrides are actually active via `.dart_tool/package_config.json`.
- Avoid assuming old logs reflect current source; reproduce after fresh build.
- When a repo mixes TS/JS and Python, only run Ruff on Python files. Do **not** point Ruff at TS/TSX/CSS; use the project’s JS/TS build/test commands (e.g., `npm run build`) for those files.

### 3) Contract-first API debugging
- Validate backend requirements and app payload schema side-by-side.
- Log outbound request payloads during failing flows (endpoint + key fields).
- Add defensive guards for required identifiers (for example trim/regenerate missing user IDs).
- Add explicit request timeout for app network calls to avoid hung UI behavior.
- **Do not swallow backend errors**: return structured error results (e.g., `Result` with message) from native commands and surface the message in UI/debug logs so permission or capability failures are visible.

### 4) UI interaction reliability
- Treat "button not clicking" as either hit-target issue or runtime-state issue; prove which.
- For Flutter lists/rows, ensure opaque hit behavior and enough bottom padding where overlays may block taps.
- Check whether system overlays (keyguard/notification shade) are intercepting input before patching app UI.

### 5) Signal over noise
- Remove or gate high-frequency debug logs from hot paths (SMS loops, render loops, polling loops).
- Keep logs that are diagnostic for flow completion: request payload, response code/body snippet, user-facing action markers.

### 6) Verify end-to-end before closing
- Verify app logs show intended request payload.
- Verify server accepts data (not only client-side success UI).
- Verify downstream read API/dashboard shows written data with the same IDs/dates.
- Document exact observed evidence (endpoint, status, key fields).

## Failure Patterns To Check Immediately
- Taps do nothing: focus is not app window; system UI is on top.
- Intermittent non-clicks: lockscreen/shade appears between automation steps.
- Persistent 400s: required field mismatch or stale build not running patched code.
- Fix exists in source but behavior unchanged: dependency override/build cache not refreshed.

## Resources
- `scripts/android_focus_preflight.sh`: quick Android focus/lockscreen/package preflight for ADB sessions.
- `references/flutter-android-failure-patterns.md`: compact checklist and command patterns learned from real failures.
