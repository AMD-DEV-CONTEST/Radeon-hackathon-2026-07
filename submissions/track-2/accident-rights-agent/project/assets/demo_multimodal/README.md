# Synthetic multimodal demo assets

These three images are AI-generated, fictional evidence fixtures. They contain
no real accident, party, vehicle record, case number, or official document.
The application labels every derived file as synthetic and must never export
these assets as real evidence.

## Prompt set

- `demo_a-intersection-v1.jpg`: neutral daylight dashcam-style view of a generic
  signalized intersection, with a compact car travelling straight and a
  two-wheel electric bicycle entering from the right.
- `demo_b-scene-v1.jpg`: neutral smartphone evidence view after minor contact;
  the two-wheel vehicle's model, parameters, and registration type are not
  visually determinable, supporting the insufficient-evidence boundary case.
- `demo_c-scene-v1.jpg`: neutral side-angle scene view with ambiguous side-road
  versus main-road geometry, supporting the conflicting-evidence boundary case.

All prompts excluded legible plates, personal identifiers, police emblems,
brand logos, official-document styling, injury, gore, captions, and watermarks.
The built-in image generation tool produced the source images; they were resized
and JPEG-compressed locally for stable project-bound use.

Each scene also has a three-second, 480x270, 2 fps H.264 MP4 dashcam fixture.
The MP4 files use baseline H.264 and `yuv420p` for browser, Android, iOS,
HarmonyOS, Windows, and macOS playback compatibility.
