#!/bin/zsh
# Reinstall the current build on the connected iPhone.
# Normal mode: incremental build. --rebuild: clean build (regenerates the free
# provisioning profile near its 7-day expiry). Any failed gate stops the script.
set -euo pipefail

export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${TMPDIR:-/tmp}/ielts-os-derived-data/Build/Products/Debug-iphoneos/App.app"
DEVICE="C7641A08-9529-5DDC-9B2D-B49CBEB72857"
DESTINATION="id=00008130-000E60643EE2001C"
BUNDLE_ID="com.francischi.ieltsos"

cd "$PROJECT_DIR"

echo "== sync web assets"
npx cap sync ios

BUILD_ACTIONS=(build)
if [[ "${1:-}" == "--rebuild" ]]; then
  BUILD_ACTIONS=(clean build)
fi
echo "== xcodebuild ${BUILD_ACTIONS}"
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Debug \
  -destination "$DESTINATION" -allowProvisioningUpdates \
  -derivedDataPath "${TMPDIR:-/tmp}/ielts-os-derived-data" "${BUILD_ACTIONS[@]}" | tail -3

[[ -d "$APP_DIR" ]] || { echo "FAIL: App.app missing at $APP_DIR"; exit 1; }

echo "== profile expiry"
security cms -D -i "$APP_DIR/embedded.mobileprovision" > /tmp/ielts-provision.plist
EXPIRY=$(/usr/libexec/PlistBuddy -c "Print :ExpirationDate" /tmp/ielts-provision.plist)
echo "   $EXPIRY (rerun with --rebuild before this date)"

echo "== verify signatures"
codesign --verify --deep --strict "$APP_DIR"
codesign -dv --verbose=4 "$APP_DIR" 2>&1 | grep -q "CandidateCDHash sha256" || { echo "FAIL: App.app missing sha256 CDHash"; exit 1; }
while IFS= read -r -d '' nested; do
  codesign --verify --strict "$nested"
  codesign -dv --verbose=4 "$nested" 2>&1 | grep -q "CandidateCDHash sha256" || { echo "FAIL: missing sha256 CDHash: $nested"; exit 1; }
done < <(find "$APP_DIR" \( -name "*.framework" -o -name "*.dylib" \) -print0)

echo "== install"
xcrun devicectl device install app --device "$DEVICE" "$APP_DIR"

echo "== launch"
xcrun devicectl device process launch --device "$DEVICE" "$BUNDLE_ID"
sleep 10
if xcrun devicectl device info processes --device "$DEVICE" | grep -q "$BUNDLE_ID"; then
  echo "OK: app running on phone"
else
  echo "FAIL: app process not found after launch"; exit 1
fi
