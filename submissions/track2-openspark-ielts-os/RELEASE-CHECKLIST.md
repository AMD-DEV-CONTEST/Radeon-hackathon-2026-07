# IELTS OS Release Checklist

## Product quality

- [ ] Complete at least one end-to-end test for vocabulary, listening, reading, writing, speaking, news reading, wrong-question review, backup, and restore.
- [ ] Test Dynamic Type, VoiceOver order, contrast, keyboard focus, offline mode, and empty/error states. Reduced-motion support is implemented.
- [ ] Validate band estimates against a scored IELTS mock cohort before presenting them as predictive.

## Services

- [ ] Deploy `local-agent-server.mjs` with either Radeon Cloud or a local Ollama/vLLM backend. Keep the model key on the server and add authentication before public hosting.
- [ ] Choose an account/cloud provider and implement sign-in, encrypted remote sync, and deletion. Local export/import merge and pre-import recovery are implemented; see `SYNC-DESIGN.md`.
- [ ] Replace the Guardian test key and confirm the intended content licence.
- [ ] Connect local error logs to a production crash-reporting provider after privacy review.

## iOS

- [x] Set the Apple Development Team and bundle identifier in Xcode for the current owner.
- [x] Restrict the learning UI to portrait, remove obsolete armv7 capability, and use a dark-content status bar.
- [ ] Test microphone and local-notification permissions on a physical iPhone.
- [ ] Add a WidgetKit extension only after the Today screen and deep links are stable.
- [ ] Add final app icon, launch screen, screenshots, support URL, privacy URL, and age rating.
- [ ] Archive a Release build, validate it, upload to App Store Connect, and invite internal TestFlight testers.
