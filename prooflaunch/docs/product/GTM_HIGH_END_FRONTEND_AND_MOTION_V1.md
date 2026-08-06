# ProofLaunch High-End Frontend and Motion Decision V1

Date: 2026-08-06  
State: implemented in the real 46-route product shell  
Truth boundary: visual and interaction quality are implemented; named-human preference and production effect remain unproven.

## Product direction

The final user-selected direction is **Luminous GTM Atelier**. The home route leaves the three-column administration shell and becomes a full-width editorial product front: oversized asymmetric typography, a single cinematic evidence work, a continuous five-stage operating sequence, and a high-density last-mile output atelier. It rejects the generic SaaS hero, logo cloud, dashboard-card mosaic, decorative gradient-as-identity pattern, and the rejected dark-template color swap.

The home surface now joins:

- the actual Evidence → Brief → Create → Verify → Export graph;
- frozen B2B and B2C GTM review specimens;
- platform-native copy, director work orders, search/GEO surfaces, lifecycle, and experiment handoff language;
- exact proof counters, including zero publication, zero named-human wins, and zero attributed production effects;
- a direct route into the real GTM cockpit rather than a detached concept page.

## Open-source motion review

| Candidate | Useful capability | Decision |
| --- | --- | --- |
| [Motion](https://github.com/motiondivision/motion) | MIT-licensed hybrid browser/JavaScript animation engine with gestures, timelines, layout and scroll effects | Reference implementation inspected; dependency not added because the current static SPA needs only a bounded subset. |
| [Barba.js](https://github.com/barbajs/barba) | MIT-licensed transition lifecycle and routing hooks | Not added: ProofLaunch already owns a deterministic same-document router, so a second routing lifecycle adds risk without product value. |
| [Lenis](https://github.com/darkroomengineering/lenis) | High-quality smooth scrolling and WebGL/scroll synchronization | Not added: the control console contains nested scroll surfaces and must preserve native scrolling, focus, and low-power behavior. |
| [View Transition API](https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API) | Native same-document state transitions with progressive enhancement | Selected for route and B2B/B2C specimen transitions. |

## Implemented motion language

1. Route changes use `document.startViewTransition` when available.
2. Unsupported browsers receive an instantaneous state change, not a broken transition.
3. `prefers-reduced-motion: reduce` disables route, reveal, hover-lift, and image-scale movement.
4. The hero artwork uses restrained transform-only movement; it does not hijack scrolling or obscure content.
5. The output forge reveals once with `IntersectionObserver`; the content remains visible without it.
6. Motion uses opacity and transforms only; no layout-critical animation or scroll hijacking is present.
7. Truth counters, blocked controls, and approval state are never animated in a way that obscures state.

## Visual contract

- Warm editorial field: `#f3f0e8`.
- Paper surface: `#f8f6ef`.
- Cobalt action and artifact plane: `#164bdf`.
- Signal yellow: `#ffcf50`.
- Evidence warning vermilion: `#e2542f`.
- Oversized architectural grotesk, italic editorial contrast, and tabular monospace evidence labels.
- The home route is structurally full-width; the operator rails return on operational routes.
- Minimum three-pixel keyboard focus ring, responsive one-column reduction, and no reliance on color alone for proof state.

## Files

- `web/index.html`: full-width GTM Atelier, five-stage operating sequence, B2B/B2C output forge, exact proof ledger.
- `web/styles.css`: cinematic visual layer, responsive behavior, reduced-motion fallback, view-transition choreography.
- `web/app.js`: progressive route transitions, specimen switching, and reveal observer.

## Acceptance boundary

This work may be described as a high-end implemented product surface. It may not be described as globally preferred, 4A-proven, or market-winning until the named-human and observed-effect gates are complete.
