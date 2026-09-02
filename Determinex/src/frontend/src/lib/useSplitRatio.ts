"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { LAYOUT_RESTORED_EVENT } from "./panelLayouts";

/**
 * A user-resizable, persisted split between two columns.
 *
 * Ryan, twice now: "all of these boxes are locked, they should be able to be
 * moved or changed or deleted or setup however the user wants. this is too locked
 * in." Zone 1 got a drag handle; the split INSIDE Zone 2 stayed a hard-coded
 * `xl:grid-cols-[1.1fr_0.9fr]`, so the only way to change it remained editing the
 * source. Documenting that as a "feature request" was papering over it.
 *
 * Ratio rather than pixel width, because this split lives inside a container that
 * is itself resizable (Zone 2 is `flex-1` and grows as Zone 1 shrinks). A stored
 * pixel width would silently stop matching the moment the window or Zone 1
 * changed; a ratio survives both.
 *
 * Same proven idiom as `usePanelWidth`: pointer drag, ref for the live value so a
 * fast drag cannot read a stale one, one localStorage commit per gesture rather
 * than per frame.
 */

const STORAGE_PREFIX = "determinex.splitRatio.";

export interface SplitRatio {
  /** Fraction of the container given to the first column, 0..1. */
  ratio: number;
  startResize: (e: { clientX: number; preventDefault: () => void }) => void;
  resizing: boolean;
  /** Restore the built-in default. */
  reset: () => void;
}

export function usePanelSplit(
  key: string,
  defaultRatio = 0.55,
  opts: { min?: number; max?: number; containerRef?: { current: HTMLElement | null } } = {}
): SplitRatio {
  const min = opts.min ?? 0.25;
  const max = opts.max ?? 0.75;

  const [ratio, setRatio] = useState(defaultRatio);
  const [resizing, setResizing] = useState(false);
  const ratioRef = useRef(defaultRatio);
  const containerWidthRef = useRef(0);

  // Read in an effect, never in the useState initializer: localStorage does not
  // exist during SSR and reading it while rendering desyncs server and client.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const read = () => {
      const raw = window.localStorage.getItem(STORAGE_PREFIX + key);
      const n = raw ? Number(raw) : NaN;
      setRatio(Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : defaultRatio);
    };
    read();
    window.addEventListener(LAYOUT_RESTORED_EVENT, read);
    return () => window.removeEventListener(LAYOUT_RESTORED_EVENT, read);
  }, [key, min, max, defaultRatio]);

  useEffect(() => {
    ratioRef.current = ratio;
  }, [ratio]);

  const commit = useCallback(
    (value: number) => {
      try {
        window.localStorage.setItem(STORAGE_PREFIX + key, String(value));
      } catch {
        /* storage disabled -- the split still applies for this session */
      }
    },
    [key]
  );

  // React Compiler declines to optimize this component while the manual memoization is
  // here ("Existing memoization could not be preserved"), and narrowing the dependency from
  // `opts` to `opts.containerRef` was not enough: the callback also closes over refs it
  // mutates during the gesture, which the compiler cannot prove it can preserve. Dropping
  // the useCallback would hand the job to the compiler, but startResize is attached to a
  // pointer-down handler and the identity churn is not free during a drag. Keeping the
  // manual memo and telling the compiler to leave this one alone is the honest trade.
  const startResize = useCallback(
    // The rule reports on the FUNCTION EXPRESSION, not on the useCallback call, so the
    // directive belongs here rather than a line above `const startResize`.
    // eslint-disable-next-line react-hooks/preserve-manual-memoization
    (e: { clientX: number; preventDefault: () => void }) => {
      e.preventDefault();
      // The grid being split is the denominator, captured once at gesture start.
      //
      // Taken from an explicit ref rather than walked from the event target: the
      // first version read `e.currentTarget.parentElement`, which silently
      // resolved to 0 width and made the handle look draggable while doing
      // nothing at all -- caught by the e2e spec, not by reading it.
      const container =
        opts.containerRef?.current ??
        (e as unknown as { currentTarget?: HTMLElement }).currentTarget?.parentElement ??
        null;
      containerWidthRef.current = container?.getBoundingClientRect().width ?? 0;
      if (containerWidthRef.current <= 0) return;

      const startX = e.clientX;
      const startRatio = ratioRef.current;
      setResizing(true);

      const onMove = (ev: PointerEvent) => {
        const delta = (ev.clientX - startX) / containerWidthRef.current;
        const next = Math.min(max, Math.max(min, startRatio + delta));
        ratioRef.current = next;
        setRatio(next);
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        setResizing(false);
        commit(ratioRef.current);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    // `opts.containerRef`, not `opts`. Callers build the options object inline, so a whole-
    // object dependency changes identity every render and React Compiler reported
    // "Existing memoization could not be preserved" and skipped optimizing this component.
    // The callback only ever reads containerRef, and a ref object is stable for the
    // component's lifetime, so this both narrows the dependency and makes it honest.
    [min, max, commit, opts.containerRef]
  );

  const reset = useCallback(() => {
    ratioRef.current = defaultRatio;
    setRatio(defaultRatio);
    commit(defaultRatio);
  }, [defaultRatio, commit]);

  return { ratio, startResize, resizing, reset };
}
