# Flutter + Android Failure Patterns

## High-value preflight
- Confirm active device: `adb devices -l`
- Confirm focused window/app:
  - `adb shell dumpsys window | rg -n "mCurrentFocus|mFocusedApp"`
- Confirm app is not blocked by SystemUI/NotificationShade before tap automation.

## Wireless ADB stability
- Prefer already-connected endpoint for the same device IP.
- Treat mDNS-discovered ports as changing values.
- If scripts hardcode `<ip>:<port>`, add fallback discovery but do not trust stale discovery over active connection.

## Build hygiene after plugin/override edits
- Run:
  - `flutter clean`
  - `flutter pub get`
  - fresh `flutter run`
- Verify overrides are active:
  - check `.dart_tool/package_config.json` for local `rootUri` paths.

## API integration guardrails
- Log full outbound payload on failing flow.
- Log non-2xx status and response snippet.
- Mirror backend required fields exactly.
- Add client timeout for each API call.

## Symptom-to-cause shortcuts
- "Nothing happens on tap": focus not on app window.
- "400 with required field missing": payload mismatch or stale binary.
- "Fix in source but behavior unchanged": old build or wrong dependency source.
- "Debugging impossible": noisy log flood from tight loop.

## Proven verification sequence
1. Trigger user action in app.
2. Capture outbound payload log with key identifiers (`userId`, date fields, endpoint).
3. Confirm server response code and body.
4. Query read endpoint/dashboard using same IDs and dates.
5. Record concrete evidence in final report.
