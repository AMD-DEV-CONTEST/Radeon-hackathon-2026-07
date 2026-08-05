# Phone Testing

## Current Milestone

The web prototype and mobile bundle share the same HTML, CSS, JavaScript, data, and audio assets.

## iPhone Installation

1. Install Xcode from the Mac App Store and open it once.
2. In this project, run `npm install`.
3. Run `npm run cap:ios` the first time, then `npm run cap:sync` after later changes.
4. Connect the iPhone by cable, run `npm run cap:open`, and select the phone as the Xcode target.
5. Choose a personal Apple development team under Signing & Capabilities, then press Run.

A free Apple ID can install a development build on a personal device. App Store distribution is a later, separate milestone.

## Browser Testing

The local URL `http://127.0.0.1:4173/` only works on this Mac. Phone browser testing needs either a LAN URL from the Mac or an HTTPS deployment. Installing the PWA to the iPhone home screen should use an HTTPS deployment.
