import {
  Check,
  ChevronDown,
  KeyRound,
  Layers3,
  LockKeyhole,
  Magnet,
  Minus,
  Plus,
  UnlockKeyhole,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { SOURCE_IMAGE } from "../data";
import type { Shot, TimelineScene } from "../types";

interface TimelineProps {
  shots: Shot[];
  scenes: TimelineScene[];
  currentTime: number;
  selectedShotId: string;
  duration: number;
  fps: number;
  currentExposure: number;
  onSeek: (time: number) => void;
  onExposureKeyframeEditStart?: (
    nodeId: string,
    keyframeIndex: number,
  ) => void;
  onExposureKeyframePreview?: (
    nodeId: string,
    keyframeIndex: number,
    time: number,
    value: number,
  ) => void;
  onExposureKeyframeCommit?: (
    nodeId: string,
    keyframeIndex: number,
    time: number,
    value: number,
  ) => void;
  onExposureKeyframeCancel?: () => void;
  onScrubChange?: (scrubbing: boolean) => void;
}

interface CurvePoint {
  x: number;
  y: number;
  time: number;
  value: number;
  nodeId: string;
  keyframeIndex: number;
  minimumTime: number;
  maximumTime: number;
}

interface KeyframePointerState {
  point: CurvePoint;
  pointerId: number;
  target: SVGCircleElement;
  startX: number;
  startY: number;
  dragging: boolean;
  latestTime: number;
  latestValue: number;
}

const KEYFRAME_DRAG_THRESHOLD_PX = 5;

function curvePointId(point: Pick<CurvePoint, "nodeId" | "keyframeIndex">) {
  return `${point.nodeId}:${point.keyframeIndex}`;
}

function endpointSlope(
  firstSpan: number,
  secondSpan: number,
  firstSecant: number,
  secondSecant: number,
): number {
  const slope =
    ((2 * firstSpan + secondSpan) * firstSecant -
      firstSpan * secondSecant) /
    (firstSpan + secondSpan);
  if (slope * firstSecant <= 0) return 0;
  if (
    firstSecant * secondSecant < 0 &&
    Math.abs(slope) > 3 * Math.abs(firstSecant)
  ) {
    return 3 * firstSecant;
  }
  return slope;
}

function pchipTrackPath(points: CurvePoint[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  const spans = points.slice(1).map((point, index) => point.x - points[index].x);
  const secants = points
    .slice(1)
    .map((point, index) => (point.y - points[index].y) / spans[index]);
  const slopes = new Array<number>(points.length).fill(0);
  if (points.length === 2) {
    slopes[0] = secants[0];
    slopes[1] = secants[0];
  } else {
    slopes[0] = endpointSlope(
      spans[0],
      spans[1],
      secants[0],
      secants[1],
    );
    slopes[slopes.length - 1] = endpointSlope(
      spans[spans.length - 1],
      spans[spans.length - 2],
      secants[secants.length - 1],
      secants[secants.length - 2],
    );
    for (let index = 1; index < points.length - 1; index += 1) {
      const previousSecant = secants[index - 1];
      const followingSecant = secants[index];
      if (
        previousSecant === 0 ||
        followingSecant === 0 ||
        previousSecant * followingSecant <= 0
      ) {
        slopes[index] = 0;
        continue;
      }
      const previousSpan = spans[index - 1];
      const followingSpan = spans[index];
      const firstWeight = 2 * followingSpan + previousSpan;
      const secondWeight = followingSpan + 2 * previousSpan;
      slopes[index] =
        (firstWeight + secondWeight) /
        (firstWeight / previousSecant + secondWeight / followingSecant);
    }
  }

  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const span = next.x - current.x;
    const control1 = {
      x: current.x + span / 3,
      y: current.y + (slopes[index] * span) / 3,
    };
    const control2 = {
      x: next.x - span / 3,
      y: next.y - (slopes[index + 1] * span) / 3,
    };
    path += ` C ${control1.x} ${control1.y}, ${control2.x} ${control2.y}, ${next.x} ${next.y}`;
  }
  return path;
}

function pchipPath(points: CurvePoint[]): string {
  const tracks: CurvePoint[][] = [];
  for (const point of points) {
    const currentTrack = tracks.at(-1);
    if (!currentTrack || currentTrack[0].nodeId !== point.nodeId) {
      tracks.push([point]);
    } else {
      currentTrack.push(point);
    }
  }
  return tracks.map(pchipTrackPath).join(" ");
}

export function Timeline({
  shots,
  scenes,
  currentTime,
  selectedShotId,
  duration,
  fps,
  currentExposure,
  onSeek,
  onExposureKeyframeEditStart,
  onExposureKeyframePreview,
  onExposureKeyframeCommit,
  onExposureKeyframeCancel,
  onScrubChange,
}: TimelineProps) {
  const curveRef = useRef<SVGSVGElement>(null);
  const tracksRef = useRef<HTMLDivElement>(null);
  const keyframePointerRef = useRef<KeyframePointerState | null>(null);
  const interactionRef = useRef<"seek" | "keyframe" | null>(null);
  const [snapEnabled, setSnapEnabled] = useState(true);
  const [showKeyframes, setShowKeyframes] = useState(true);
  const [keyframeEditMode, setKeyframeEditMode] = useState(false);
  const [selectedKeyframeId, setSelectedKeyframeId] = useState<string | null>(
    null,
  );
  const [exactTime, setExactTime] = useState("");
  const [exactValue, setExactValue] = useState("");
  const [isScrubbing, setIsScrubbing] = useState(false);
  const safeDuration = Math.max(duration, 0.001);
  const markStep =
    safeDuration <= 10 ? 2 : safeDuration <= 30 ? 5 : safeDuration <= 90 ? 15 : 30;
  const marks = Array.from(
    { length: Math.floor(safeDuration / markStep) + 1 },
    (_, index) => index * markStep,
  );
  const playhead = Math.max(
    0,
    Math.min(100, (currentTime / safeDuration) * 100),
  );
  const activeScene =
    scenes.find(
      (scene) =>
        currentTime >= scene.start &&
        currentTime < scene.start + scene.duration,
    ) ?? scenes.at(-1);
  const keyframes = shots
    .flatMap((shot) => {
      const frames = shot.exposureKeyframes ?? [];
      return frames.map((keyframe, index) => ({
        ...keyframe,
        minimumTime: Math.max(
          shot.start,
          index > 0 ? frames[index - 1].time + 0.01 : shot.start,
        ),
        maximumTime: Math.min(
          shot.start + shot.duration,
          index < frames.length - 1
            ? frames[index + 1].time - 0.01
            : shot.start + shot.duration,
        ),
      }));
    })
    .sort((left, right) => left.time - right.time);
  const values = keyframes.map((keyframe) => keyframe.value);
  const minimum = Math.min(...values, -2);
  const maximum = Math.max(...values, 2);
  const span = Math.max(maximum - minimum, 0.25);
  const curvePoints = keyframes.map((keyframe) => ({
    x: (keyframe.time / safeDuration) * 1000,
    y: 49 - ((keyframe.value - minimum) / span) * 36,
    time: keyframe.time,
    value: keyframe.value,
    nodeId: keyframe.nodeId,
    keyframeIndex: keyframe.keyframeIndex,
    minimumTime: keyframe.minimumTime,
    maximumTime: keyframe.maximumTime,
  }));
  const curvePath = pchipPath(curvePoints);

  const setInteraction = (interaction: "seek" | "keyframe" | null) => {
    if (interactionRef.current === interaction) return;
    interactionRef.current = interaction;
    const nextScrubbing = interaction !== null;
    setIsScrubbing(nextScrubbing);
    onScrubChange?.(nextScrubbing);
  };

  const normalizedSeekTime = (time: number, snap = snapEnabled) => {
    let nextTime = Math.max(0, Math.min(duration, time));
    if (snap && fps > 0) {
      nextTime = Math.round(nextTime * fps) / fps;
      nextTime = Math.max(0, Math.min(duration, nextTime));
    }
    return Number(nextTime.toFixed(6));
  };

  const seekFromClientX = (clientX: number) => {
    const bounds = tracksRef.current?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || duration <= 0) return;
    const ratio = Math.max(
      0,
      Math.min(1, (clientX - bounds.left) / bounds.width),
    );
    onSeek(normalizedSeekTime(ratio * duration));
  };

  const beginTimelineScrub = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0 || duration <= 0 || interactionRef.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setInteraction("seek");
    seekFromClientX(event.clientX);
  };

  const moveTimelineScrub = (event: ReactPointerEvent<HTMLElement>) => {
    if (interactionRef.current !== "seek") return;
    event.preventDefault();
    seekFromClientX(event.clientX);
  };

  const finishTimelineScrub = (
    event: ReactPointerEvent<HTMLElement>,
    updateTime: boolean,
  ) => {
    if (interactionRef.current !== "seek") return;
    if (updateTime) seekFromClientX(event.clientX);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setInteraction(null);
  };

  const keyframeValueFromPointer = (
    clientX: number,
    clientY: number,
    point: CurvePoint,
  ) => {
    const bounds = curveRef.current?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) {
      return { time: point.time, value: point.value };
    }
    const xRatio = Math.max(
      0,
      Math.min(1, (clientX - bounds.left) / bounds.width),
    );
    const yRatio = Math.max(
      0,
      Math.min(1, (clientY - bounds.top) / bounds.height),
    );
    let time = Math.max(
      point.minimumTime,
      Math.min(point.maximumTime, xRatio * safeDuration),
    );
    if (snapEnabled && fps > 0) {
      time = Math.round(time * fps) / fps;
      time = Math.max(point.minimumTime, Math.min(point.maximumTime, time));
    }
    return {
      time: Number(time.toFixed(4)),
      value: Number((maximum - yRatio * span).toFixed(4)),
    };
  };

  const beginKeyframePointer = (
    event: ReactPointerEvent<SVGCircleElement>,
    point: CurvePoint,
  ) => {
    event.stopPropagation();
    if (event.button !== 0) return;
    event.preventDefault();
    if (
      !keyframeEditMode ||
      !onExposureKeyframeEditStart ||
      !onExposureKeyframePreview ||
      !onExposureKeyframeCommit ||
      interactionRef.current
    ) {
      onSeek(point.time);
      return;
    }
    const pointId = curvePointId(point);
    event.currentTarget.focus();
    if (selectedKeyframeId !== pointId) {
      setSelectedKeyframeId(pointId);
      setExactTime(point.time.toFixed(4));
      setExactValue(point.value.toFixed(4));
      onSeek(point.time);
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    keyframePointerRef.current = {
      point,
      pointerId: event.pointerId,
      target: event.currentTarget,
      startX: event.clientX,
      startY: event.clientY,
      dragging: false,
      latestTime: point.time,
      latestValue: point.value,
    };
  };

  const updateDraggedKeyframe = (
    event: ReactPointerEvent<SVGSVGElement>,
  ) => {
    const pointer = keyframePointerRef.current;
    if (
      !pointer ||
      pointer.pointerId !== event.pointerId ||
      !onExposureKeyframeEditStart ||
      !onExposureKeyframePreview
    ) {
      return;
    }
    if (!pointer.dragging) {
      const distance = Math.hypot(
        event.clientX - pointer.startX,
        event.clientY - pointer.startY,
      );
      if (distance < KEYFRAME_DRAG_THRESHOLD_PX) return;
      pointer.dragging = true;
      onExposureKeyframeEditStart(
        pointer.point.nodeId,
        pointer.point.keyframeIndex,
      );
      setInteraction("keyframe");
    }
    const next = keyframeValueFromPointer(
      event.clientX,
      event.clientY,
      pointer.point,
    );
    pointer.latestTime = next.time;
    pointer.latestValue = next.value;
    onExposureKeyframePreview(
      pointer.point.nodeId,
      pointer.point.keyframeIndex,
      next.time,
      next.value,
    );
    onSeek(next.time);
  };

  const finishKeyframePointer = (
    event: ReactPointerEvent<SVGCircleElement>,
    commit: boolean,
  ) => {
    event.stopPropagation();
    const pointer = keyframePointerRef.current;
    if (!pointer || pointer.pointerId !== event.pointerId) return;
    keyframePointerRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (pointer.dragging) {
      if (commit && onExposureKeyframeCommit) {
        onExposureKeyframeCommit(
          pointer.point.nodeId,
          pointer.point.keyframeIndex,
          pointer.latestTime,
          pointer.latestValue,
        );
      } else {
        onExposureKeyframeCancel?.();
      }
    } else if (commit) {
      onSeek(pointer.point.time);
    }
    setInteraction(null);
  };

  const cancelKeyframePointer = () => {
    const pointer = keyframePointerRef.current;
    if (!pointer) return false;
    keyframePointerRef.current = null;
    if (pointer.target.hasPointerCapture(pointer.pointerId)) {
      pointer.target.releasePointerCapture(pointer.pointerId);
    }
    if (pointer.dragging) onExposureKeyframeCancel?.();
    setInteraction(null);
    return true;
  };

  const changeFromKeyboard = (
    event: ReactKeyboardEvent<SVGCircleElement>,
    point: CurvePoint,
  ) => {
    if (!keyframeEditMode) return;
    const pointId = curvePointId(point);
    if (
      event.key === "Enter" ||
      event.key === " " ||
      selectedKeyframeId !== pointId
    ) {
      if (
        event.key === "Enter" ||
        event.key === " " ||
        event.key.startsWith("Arrow")
      ) {
        event.preventDefault();
        event.stopPropagation();
        setSelectedKeyframeId(pointId);
        setExactTime(point.time.toFixed(4));
        setExactValue(point.value.toFixed(4));
        onSeek(point.time);
      }
      return;
    }
    if (!onExposureKeyframeEditStart || !onExposureKeyframeCommit) return;
    const frameStep = fps > 0 ? 1 / fps : 0.04;
    let time = point.time;
    let value = point.value;
    if (event.key === "ArrowLeft") time -= frameStep;
    else if (event.key === "ArrowRight") time += frameStep;
    else if (event.key === "ArrowUp") value += 0.05;
    else if (event.key === "ArrowDown") value -= 0.05;
    else return;
    event.preventDefault();
    event.stopPropagation();
    time = Math.max(point.minimumTime, Math.min(point.maximumTime, time));
    const nextTime = Number(time.toFixed(4));
    const nextValue = Number(value.toFixed(4));
    onExposureKeyframeEditStart(point.nodeId, point.keyframeIndex);
    onExposureKeyframeCommit(
      point.nodeId,
      point.keyframeIndex,
      nextTime,
      nextValue,
    );
    onSeek(nextTime);
  };

  const movePlayheadFromKeyboard = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
  ) => {
    const frameStep = fps > 0 ? 1 / fps : 0.04;
    let nextTime = currentTime;
    if (event.key === "ArrowLeft") nextTime -= frameStep;
    else if (event.key === "ArrowRight") nextTime += frameStep;
    else if (event.key === "Home") nextTime = 0;
    else if (event.key === "End") nextTime = duration;
    else return;
    event.preventDefault();
    event.stopPropagation();
    onSeek(normalizedSeekTime(nextTime, false));
  };

  const selectedPoint = selectedKeyframeId
    ? curvePoints.find((point) => curvePointId(point) === selectedKeyframeId)
    : undefined;

  useEffect(() => {
    if (!selectedKeyframeId) return;
    if (!selectedPoint) {
      setSelectedKeyframeId(null);
      setExactTime("");
      setExactValue("");
      return;
    }
    setExactTime(selectedPoint.time.toFixed(4));
    setExactValue(selectedPoint.value.toFixed(4));
  }, [
    selectedKeyframeId,
    selectedPoint?.time,
    selectedPoint?.value,
  ]);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (cancelKeyframePointer()) {
        event.preventDefault();
        return;
      }
      if (keyframeEditMode && selectedKeyframeId) {
        setSelectedKeyframeId(null);
        setExactTime("");
        setExactValue("");
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  });

  const applyExactKeyframeValue = () => {
    if (
      !selectedPoint ||
      !onExposureKeyframeEditStart ||
      !onExposureKeyframeCommit
    ) {
      return;
    }
    const parsedTime = Number(exactTime);
    const parsedValue = Number(exactValue);
    if (!Number.isFinite(parsedTime) || !Number.isFinite(parsedValue)) return;
    const time = Number(
      Math.max(
        selectedPoint.minimumTime,
        Math.min(selectedPoint.maximumTime, parsedTime),
      ).toFixed(4),
    );
    const value = Number(Math.max(-8, Math.min(8, parsedValue)).toFixed(4));
    onExposureKeyframeEditStart(
      selectedPoint.nodeId,
      selectedPoint.keyframeIndex,
    );
    onExposureKeyframeCommit(
      selectedPoint.nodeId,
      selectedPoint.keyframeIndex,
      time,
      value,
    );
    setExactTime(time.toFixed(4));
    setExactValue(value.toFixed(4));
    onSeek(time);
  };

  const toggleKeyframeEditMode = () => {
    if (keyframeEditMode) {
      cancelKeyframePointer();
      setSelectedKeyframeId(null);
      setExactTime("");
      setExactValue("");
    }
    setKeyframeEditMode((enabled) => !enabled);
  };

  return (
    <section className="timeline-shell">
      <div className="timeline-toolbar">
        <div className="timeline-title">
          <Layers3 size={14} />
          <span>{activeScene?.label ?? "No Scene"}</span>
          <ChevronDown size={12} />
          <i />
          <strong>
            {scenes.length} 场景 · {shots.length} 镜头
          </strong>
        </div>
        <div className="timeline-actions">
          <span
            className={`keyframe-mode-status ${
              keyframeEditMode ? "is-editing" : ""
            }`}
          >
            {keyframeEditMode ? "Exposure 编辑" : "Exposure 已锁定"}
          </span>
          <button
            className={keyframeEditMode ? "is-active" : ""}
            type="button"
            aria-label={
              keyframeEditMode ? "锁定 Exposure 关键帧" : "编辑 Exposure 关键帧"
            }
            aria-pressed={keyframeEditMode}
            disabled={
              !onExposureKeyframeEditStart ||
              !onExposureKeyframePreview ||
              !onExposureKeyframeCommit
            }
            title={
              keyframeEditMode
                ? "退出编辑并恢复只读"
                : "解锁后先选择关键帧，再拖动或精确输入"
            }
            onClick={toggleKeyframeEditMode}
          >
            {keyframeEditMode ? (
              <UnlockKeyhole size={13} />
            ) : (
              <LockKeyhole size={13} />
            )}
          </button>
          <button
            className={snapEnabled ? "is-active" : ""}
            type="button"
            aria-label={snapEnabled ? "关闭帧吸附" : "开启帧吸附"}
            onClick={() => setSnapEnabled((enabled) => !enabled)}
          >
            <Magnet size={13} />
          </button>
          <button
            className={showKeyframes ? "is-active" : ""}
            type="button"
            aria-label={showKeyframes ? "隐藏关键帧" : "显示关键帧"}
            onClick={() => setShowKeyframes((visible) => !visible)}
          >
            <KeyRound size={13} />
          </button>
          <div className="timeline-zoom">
            <button type="button" aria-label="缩小" disabled title="当前 MVP 使用适配视图">
              <Minus size={11} />
            </button>
            <span>
              <i />
            </span>
            <button type="button" aria-label="放大" disabled title="当前 MVP 使用适配视图">
              <Plus size={11} />
            </button>
          </div>
        </div>
      </div>

      <div className="timeline-body">
        <div className="track-labels">
          <div className="track-label scene-label">
            <span>SCENE</span>
            <strong>场景</strong>
          </div>
          <div className="track-label">
            <span>VIDEO 01</span>
            <strong>镜头</strong>
          </div>
          <div className="track-label">
            <span>EXPOSURE</span>
            <strong>Exposure · EV</strong>
          </div>
        </div>

        <div
          ref={tracksRef}
          className={`tracks ${isScrubbing ? "is-scrubbing" : ""}`}
          onPointerDown={beginTimelineScrub}
          onPointerMove={moveTimelineScrub}
          onPointerUp={(event) => finishTimelineScrub(event, true)}
          onPointerCancel={(event) => finishTimelineScrub(event, false)}
          onLostPointerCapture={() => {
            if (interactionRef.current === "seek") setInteraction(null);
          }}
        >
          <div className="time-ruler">
            {marks.map((mark) => (
              <span
                key={mark}
                className="time-mark"
                style={{ left: `${(mark / safeDuration) * 100}%` }}
                aria-hidden="true"
              >
                <i />
                <span>00:{mark.toString().padStart(2, "0")}</span>
              </span>
            ))}
          </div>

          <div className="scene-track">
            {scenes.map((scene) => (
              <div
                key={scene.id}
                className="scene-block"
                style={{ width: `${(scene.duration / safeDuration) * 100}%` }}
              >
                <span>{scene.label.toUpperCase()}</span>
                <strong>{scene.look}</strong>
              </div>
            ))}
          </div>

          <div className="shot-track">
            {shots.map((shot) => (
              <div
                key={shot.id}
                className={`shot-clip ${
                  selectedShotId === shot.id ? "is-selected" : ""
                }`}
                style={{ width: `${(shot.duration / safeDuration) * 100}%` }}
              >
                <span
                  className="shot-thumb"
                  style={{
                    backgroundImage: `linear-gradient(90deg, rgba(8,8,7,.15), rgba(8,8,7,0)), url(${shot.thumbnail ?? SOURCE_IMAGE})`,
                    backgroundPosition: shot.position,
                  }}
                />
                <span className="shot-number">{shot.label}</span>
                <span className="shot-duration">{shot.duration.toFixed(1)}s</span>
              </div>
            ))}
          </div>

          <div className="parameter-track">
            <div className="parameter-name">Exposure · EV</div>
            <svg
              ref={curveRef}
              viewBox="0 0 1000 62"
              preserveAspectRatio="none"
              onPointerMove={updateDraggedKeyframe}
            >
              <path
                className="curve-shadow"
                d={curvePath}
              />
              <path
                className="curve-line"
                d={curvePath}
              />
              {showKeyframes && (
                <g
                  className={`curve-points ${
                    keyframeEditMode ? "is-editable" : "is-locked"
                  }`}
                >
                  {curvePoints.map((point, index) => (
                    <circle
                      key={`${point.nodeId}-${point.keyframeIndex}-${index}`}
                      className={
                        selectedKeyframeId === curvePointId(point)
                          ? "is-selected"
                          : undefined
                      }
                      cx={point.x}
                      cy={point.y}
                      r="3"
                      tabIndex={keyframeEditMode ? 0 : -1}
                      aria-label={`Exposure 关键帧 ${index + 1}，${point.time.toFixed(4)} 秒，${point.value.toFixed(4)} EV${
                        keyframeEditMode ? "，可编辑" : "，轨道已锁定"
                      }`}
                      onPointerDown={(event) =>
                        beginKeyframePointer(event, point)
                      }
                      onPointerUp={(event) =>
                        finishKeyframePointer(event, true)
                      }
                      onPointerCancel={(event) =>
                        finishKeyframePointer(event, false)
                      }
                      onLostPointerCapture={() => {
                        const pointer = keyframePointerRef.current;
                        if (
                          pointer?.point.nodeId === point.nodeId &&
                          pointer.point.keyframeIndex === point.keyframeIndex
                        ) {
                          cancelKeyframePointer();
                        }
                      }}
                      onKeyDown={(event) => changeFromKeyboard(event, point)}
                    />
                  ))}
                </g>
              )}
            </svg>
            {keyframeEditMode && selectedPoint && (
              <div
                className="keyframe-exact-editor"
                onPointerDown={(event) => event.stopPropagation()}
              >
                <strong>Exposure · KF {selectedPoint.keyframeIndex + 1}</strong>
                <label>
                  <span>时间</span>
                  <input
                    type="number"
                    min={selectedPoint.minimumTime}
                    max={selectedPoint.maximumTime}
                    step={fps > 0 ? 1 / fps : 0.001}
                    value={exactTime}
                    aria-label="关键帧精确时间"
                    onChange={(event) => setExactTime(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") applyExactKeyframeValue();
                      if (event.key === "Escape") {
                        setExactTime(selectedPoint.time.toFixed(4));
                        setExactValue(selectedPoint.value.toFixed(4));
                      }
                    }}
                  />
                  <i>s</i>
                </label>
                <label>
                  <span>曝光</span>
                  <input
                    type="number"
                    min="-8"
                    max="8"
                    step="0.01"
                    value={exactValue}
                    aria-label="关键帧精确曝光"
                    onChange={(event) => setExactValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") applyExactKeyframeValue();
                      if (event.key === "Escape") {
                        setExactTime(selectedPoint.time.toFixed(4));
                        setExactValue(selectedPoint.value.toFixed(4));
                      }
                    }}
                  />
                  <i>EV</i>
                </label>
                <button
                  type="button"
                  aria-label="应用精确关键帧值"
                  title="原子提交时间与曝光"
                  onClick={applyExactKeyframeValue}
                >
                  <Check size={11} />
                </button>
                <button
                  type="button"
                  aria-label="取消选择关键帧"
                  title="取消选择"
                  onClick={() => setSelectedKeyframeId(null)}
                >
                  <X size={11} />
                </button>
              </div>
            )}
            <div className="parameter-meta">
              <span>
                {keyframes.length
                  ? `${currentExposure >= 0 ? "+" : ""}${currentExposure.toFixed(2)}`
                  : "—"}
              </span>
              <i>{keyframes.length ? "PCHIP · 单调" : "等待轨道"}</i>
            </div>
          </div>

          <button
            type="button"
            className="timeline-playhead"
            style={{ left: `${playhead}%` }}
            aria-label="播放指针"
            aria-valuemin={0}
            aria-valuemax={duration}
            aria-valuenow={Number(currentTime.toFixed(6))}
            aria-valuetext={`${currentTime.toFixed(3)} 秒`}
            role="slider"
            disabled={duration <= 0}
            title="拖动定位；左右方向键逐帧微调"
            onPointerDown={(event) => {
              event.stopPropagation();
              event.currentTarget.focus();
              beginTimelineScrub(event);
            }}
            onPointerMove={(event) => {
              event.stopPropagation();
              moveTimelineScrub(event);
            }}
            onPointerUp={(event) => {
              event.stopPropagation();
              finishTimelineScrub(event, true);
            }}
            onPointerCancel={(event) => {
              event.stopPropagation();
              finishTimelineScrub(event, false);
            }}
            onLostPointerCapture={() => {
              if (interactionRef.current === "seek") setInteraction(null);
            }}
            onKeyDown={movePlayheadFromKeyboard}
          >
            <span />
          </button>
        </div>
      </div>
    </section>
  );
}
