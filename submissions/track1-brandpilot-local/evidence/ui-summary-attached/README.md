# Attached Campaign Summary UI evidence

This folder contains sanitised local Chrome screenshots used to verify that the
Creative Studio Campaign Summary remains attached to the right rail, does not
overlap adjacent cards, and returns to normal single-column flow at responsive
widths. No authenticated pages, access codes, private URLs, browser profile
details, client assets, or Radeon runtime information are included.

The screenshot hashes are recorded in `screenshot-hashes.json`.

## Browser QA

Chrome was checked at logical viewport widths 1440, 1280, 1024, 768, 520,
430, 390, and 360 pixels. The 1280/125 capture represents the effective
1024-pixel CSS viewport produced by 125% browser zoom. The full zoom matrix
(80%, 90%, 100%, 110%, 125%, and 150%) was checked using equivalent effective
CSS viewports so responsive breakpoints, text wrapping, and card geometry match
the requested zoom conditions despite the connected Chrome session's existing
display scaling.

At every size and zoom level:

- the Campaign Summary used `position: static` and no transform;
- the right rail remained a column flex stack with a visible gap;
- the summary remained inside the rail and did not overlap the form or Radeon
  connection card;
- Radeon inputs and buttons remained visible;
- no horizontal overflow or application console errors were present; and
- the rail moved naturally with page scrolling.

The desktop image is a viewport capture. Stacked tablet/mobile evidence uses
full-page captures so the form-to-summary-to-Radeon document order is visible.
