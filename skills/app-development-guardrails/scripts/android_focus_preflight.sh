#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB_PATH:-$HOME/Library/Android/sdk/platform-tools/adb}"
TARGET_PACKAGE="${1:-}"

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "ERROR: adb not found at $ADB"
  exit 2
fi

DEVICES="$($ADB devices | awk 'NR>1 && $2=="device" {print $1}')"
if [ -z "$DEVICES" ]; then
  echo "ERROR: no connected adb devices"
  exit 3
fi

DEV="$(echo "$DEVICES" | head -n1)"
FOCUS="$($ADB -s "$DEV" shell dumpsys window | sed -n 's/.*mCurrentFocus=//p' | head -n1)"
FAPP="$($ADB -s "$DEV" shell dumpsys window | sed -n 's/.*mFocusedApp=//p' | head -n1)"

LOCK_HINT="$($ADB -s "$DEV" shell dumpsys window policy 2>/dev/null | rg -n 'isStatusBarKeyguard|mShowingLockscreen|mDreamingLockscreen' -i || true)"

echo "device: $DEV"
echo "current_focus: $FOCUS"
echo "focused_app: $FAPP"
if [ -n "$LOCK_HINT" ]; then
  echo "lockscreen_signals:"
  echo "$LOCK_HINT"
fi

if echo "$FOCUS" | rg -qi 'NotificationShade|StatusBar|com\.android\.systemui'; then
  echo "WARN: system UI appears to be focused; input taps may not reach app."
  echo "Suggested recovery:"
  echo "  $ADB -s $DEV shell input keyevent KEYCODE_BACK"
  echo "  $ADB -s $DEV shell input keyevent KEYCODE_HOME"
fi

if [ -n "$TARGET_PACKAGE" ]; then
  if echo "$FOCUS" | rg -q "$TARGET_PACKAGE"; then
    echo "ok: target package appears focused"
  else
    echo "WARN: target package '$TARGET_PACKAGE' is not focused"
    echo "Launch command:"
    echo "  $ADB -s $DEV shell monkey -p $TARGET_PACKAGE -c android.intent.category.LAUNCHER 1"
    exit 1
  fi
fi
