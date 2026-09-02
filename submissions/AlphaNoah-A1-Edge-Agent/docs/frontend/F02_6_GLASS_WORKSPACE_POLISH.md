# F02.6 Glass Workspace Polish

## Scope

F02.6 is a visual, interaction, accessibility, and test refinement of the
existing F02.5 Workspace. It adds no business capability and makes no changes
to Runtime, API, SQLite, Python, Docker, or the frontend dependency graph.

The work used isolated roles in this order:

1. Visual Review established the baseline without editing.
2. Visual Implementation changed the production frontend.
3. Automated Testing added regression coverage and reported defects.
4. Visual Review performed an independent post-implementation review.
5. The coordinator closed every Blocker and Major and regenerated evidence.
6. Visual Review performed a read-only closing verification and returned
   `READY`.

## Baseline and outcome

The baseline was `READY WITH FIXES`. It identified weak glass separation,
table-like event presentation, lost status context at 1024px, a dropdown-like
Pulse, and undersized metadata.

The first post-implementation review returned `NOT READY` because the Pulse
expanded screenshot was clipped, the Pulse-to-panel focus chain was unstable,
the 1024px status was duplicated, the lifecycle track was too long, and the
visual evidence did not prove real idle, hover, and selected states.

The coordinator fixed those mandatory findings. Final review returned
`READY`, with no remaining Blocker or Major.

## Semantic glass and motion

The shared token layer defines:

- `glass-base`: low-interference shell and instruction surfaces;
- `glass-card`: readable event field;
- `glass-focus`: selected and expanded focus context;
- `glass-overlay`: highest floating action context.

Each layer centralizes background transparency, blur, border, inner highlight,
outer shadow, and radius. Light and dark themes use the same hierarchy with
theme-specific values. Component styles do not introduce local colors, blur,
or shadows.

Motion is centralized around fast, normal, and slow durations, standard and
emphasized easing, and gentle/panel spring presets. Settling effects run once;
there are no infinite animations. User-selected reduced motion disables
nonessential transitions and transforms.

## Interaction changes

- Event rows distinguish attention, history, hover, focus, selected, and
  pressed states without relying on color alone.
- Lifecycle tracks are capped at 14rem, keep completed/current/future stages
  legible, and collapse without duplicating Runtime status at 1024px.
- Smart instruction input, submit action, and quick commands expose visible
  focus, hover, disabled, and pressed feedback while remaining local-only.
- Noah Pulse idle is a non-interactive status. Attention is an interactive
  dialog trigger. Expanded Pulse is a non-modal structured dialog in the same
  shell.
- Opening the Action Panel collapses Pulse first and uses the re-mounted
  capsule as the stable keyboard focus return target.

## Verification evidence

Visual evidence is generated under `tmp/f02.6-visual/` and is intentionally not
committed. It covers:

- dark and light at 1440×900;
- Chinese and English at 1366×768;
- layout checks at 1024×768 and 1920×1080;
- real Pulse idle, attention, and expanded states;
- real event hover and selected states.

The idle screenshot was made from a temporary build with
`notice={undefined}` and the source was restored before final validation. The
hover screenshot used a real pointer hover. No screenshot-only production
code remains.

Automated coverage includes preferences, system theme, locale, reduced motion,
event selection, keyboard focus, Pulse semantics and focus restoration, smart
instruction locality, and the absence of a real network request.

## Deferred minor items

- Desktop rows can repeat a similar Runtime and lifecycle word around the
  compact track; the meaning is correct but could be made terser later.
- Long English Pulse notice titles truncate in the compact capsule; F03 may
  add a dedicated short notice title.
- F03 may add Pulse queueing, priority, approval, and critical behavior, but
  those remain outside this static mock boundary.
