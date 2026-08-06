import {
  AlertTriangle,
  ChevronDown,
  Eye,
  Focus,
  LoaderCircle,
  Maximize2,
  Pause,
  Play,
  Repeat2,
  SlidersHorizontal,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import type {
  MaskKind,
  MediaKind,
  PreviewEncodingPreference,
  PreviewPlaybackProfile,
  PreviewPlaybackSegment,
  PreviewPlaybackTelemetry,
  PreviewQuality,
  PreviewQualityPreference,
} from "../types";

type PlaybackStatus =
  | "empty"
  | "loading"
  | "ready"
  | "buffering"
  | "playing"
  | "unsupported"
  | "error";

interface PreviewProps {
  source: string;
  gradedPlaybackSegments: PreviewPlaybackSegment[];
  gradedPlaybackGroupKey?: string;
  gradedPlaybackBufferReady: boolean;
  gradedPlaybackBufferedAhead: number;
  gradedSource?: string;
  originalSource?: string;
  previewTime?: number;
  isPreviewLoading: boolean;
  isGradedPlaybackRendering: boolean;
  gradedPlaybackProgress: number;
  maskSource?: string;
  mediaKind: MediaKind;
  mediaRef: RefObject<HTMLVideoElement | null>;
  comparePosition: number;
  mask: MaskKind;
  isPlaying: boolean;
  isMuted: boolean;
  isLooping: boolean;
  usesBrowserProxy: boolean;
  previewQuality: PreviewQuality;
  previewQualityPreference: PreviewQualityPreference;
  previewQualityOptions: PreviewQuality[];
  previewQualityEnabled: boolean;
  previewEncodingPreference: PreviewEncodingPreference;
  previewProfile: PreviewPlaybackProfile;
  previewCapabilityMessage: string;
  currentTime: number;
  duration: number;
  shotLabel?: string;
  resolution?: string;
  fps?: number;
  onCompareChange: (position: number) => void;
  onMaskChange: (mask: MaskKind) => void;
  onTogglePlay: () => void;
  onToggleMute: () => void;
  onToggleLoop: () => void;
  onPreviewQualityChange: (quality: PreviewQualityPreference) => void;
  onPreviewEncodingChange: (
    preference: PreviewEncodingPreference,
  ) => void;
  onPlaybackChange: (playing: boolean) => void;
  onMediaTimeChange: (time: number) => void;
  onPlaybackError: (message: string) => void;
  onPlaybackTelemetry: (telemetry: PreviewPlaybackTelemetry) => void;
}

function telemetrySessionId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function playbackFrameCounts(media: HTMLVideoElement): {
  total: number;
  dropped: number;
} {
  if (typeof media.getVideoPlaybackQuality === "function") {
    const quality = media.getVideoPlaybackQuality();
    return {
      total: quality.totalVideoFrames,
      dropped: quality.droppedVideoFrames,
    };
  }
  const fallback = media as HTMLVideoElement & {
    webkitDecodedFrameCount?: number;
    webkitDroppedFrameCount?: number;
  };
  return {
    total: fallback.webkitDecodedFrameCount ?? 0,
    dropped: fallback.webkitDroppedFrameCount ?? 0,
  };
}

function segmentAtTime(
  segments: PreviewPlaybackSegment[],
  timeSeconds: number,
  durationSeconds: number,
) {
  return segments.find(
    (segment) =>
      timeSeconds + 1e-6 >= segment.start_seconds &&
      (timeSeconds < segment.end_seconds ||
        (segment.end_seconds >= durationSeconds - 1e-6 &&
          timeSeconds <= segment.end_seconds + 1e-3)),
  );
}

function playbackSegmentWindow(
  segments: PreviewPlaybackSegment[],
  timeSeconds: number,
  durationSeconds: number,
  looping: boolean,
) {
  const active = segmentAtTime(segments, timeSeconds, durationSeconds);
  if (!active) return [];
  const next =
    segments.find(
      (segment) =>
        Math.abs(segment.start_seconds - active.end_seconds) < 1e-3,
    ) ??
    (looping && active.end_seconds >= durationSeconds - 1e-3
      ? segmentAtTime(segments, 0, durationSeconds)
      : undefined);
  return next && next.cache_key !== active.cache_key
    ? [active, next]
    : [active];
}

function formatTimecode(seconds: number, fps: number) {
  const safeFps = Math.max(1, fps);
  const safe = Math.max(0, seconds);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = Math.floor(safe % 60);
  const frames = Math.min(
    Math.max(0, Math.round(safeFps) - 1),
    Math.floor((safe % 1) * safeFps),
  );
  return [hours, minutes, secs, frames]
    .map((value) => value.toString().padStart(2, "0"))
    .join(":");
}

function mediaErrorMessage(media: HTMLVideoElement): {
  status: PlaybackStatus;
  message: string;
} {
  switch (media.error?.code) {
    case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
      return {
        status: "unsupported",
        message: "浏览器不支持此编码，项目需要 H.264 代理",
      };
    case MediaError.MEDIA_ERR_DECODE:
      return { status: "error", message: "媒体解码失败，请重新生成代理" };
    case MediaError.MEDIA_ERR_NETWORK:
      return { status: "error", message: "媒体读取中断，请检查本地服务" };
    default:
      return { status: "error", message: "媒体加载失败" };
  }
}

function statusLabel(
  status: PlaybackStatus,
  {
    usesBrowserProxy,
    previewQuality,
    previewProfile,
    exactStillVisible,
    previewLoading,
    gradedPlaybackReady,
    gradedPlaybackRendering,
    gradedPlaybackProgress,
    gradedPlaybackBufferedAhead,
  }: {
    usesBrowserProxy: boolean;
    previewQuality: PreviewQuality;
    previewProfile: PreviewPlaybackProfile;
    exactStillVisible: boolean;
    previewLoading: boolean;
    gradedPlaybackReady: boolean;
    gradedPlaybackRendering: boolean;
    gradedPlaybackProgress: number;
    gradedPlaybackBufferedAhead: number;
  },
) {
  if (status === "unsupported") return "编码不支持";
  if (status === "error") return "加载失败";
  if (previewLoading) return "单帧渲染中";
  if (exactStillVisible) return "精确单帧";
  if (gradedPlaybackRendering) {
    return `真实调色缓存 ${Math.round(gradedPlaybackProgress)}%`;
  }
  if (!gradedPlaybackReady) return "等待真实调色缓存";
  if (status === "buffering") return "缓冲中";
  if (status === "loading") {
    return usesBrowserProxy
      ? `载入 ${previewQuality} ${previewProfile.codec === "hevc" ? "HEVC" : "H.264"}`
      : "载入媒体";
  }
  if (status === "playing") {
    return `${previewQuality} ${previewProfile.codec === "hevc" ? "HEVC" : "H.264"} · 已缓存 ${Math.max(0, Math.round(gradedPlaybackBufferedAhead))} 秒`;
  }
  if (status === "ready") {
    return `${previewQuality} ${previewProfile.codec === "hevc" ? "HEVC" : "H.264"} 就绪 · ${Math.max(0, Math.round(gradedPlaybackBufferedAhead))} 秒`;
  }
  return "未载入媒体";
}

export function Preview({
  source,
  gradedPlaybackSegments,
  gradedPlaybackGroupKey,
  gradedPlaybackBufferReady,
  gradedPlaybackBufferedAhead,
  gradedSource,
  originalSource,
  previewTime,
  isPreviewLoading,
  isGradedPlaybackRendering,
  gradedPlaybackProgress,
  maskSource,
  mediaKind,
  mediaRef,
  comparePosition,
  mask,
  isPlaying,
  isMuted,
  isLooping,
  usesBrowserProxy,
  previewQuality,
  previewQualityPreference,
  previewQualityOptions,
  previewQualityEnabled,
  previewEncodingPreference,
  previewProfile,
  previewCapabilityMessage,
  currentTime,
  duration,
  shotLabel = "SHOT 03",
  resolution = "3840 × 2160",
  fps = 25,
  onCompareChange,
  onMaskChange,
  onTogglePlay,
  onToggleMute,
  onToggleLoop,
  onPreviewQualityChange,
  onPreviewEncodingChange,
  onPlaybackChange,
  onMediaTimeChange,
  onPlaybackError,
  onPlaybackTelemetry,
}: PreviewProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const gradedVideoRefs = useRef(new Map<string, HTMLVideoElement>());
  const activeGradedKeyRef = useRef<string | null>(null);
  const segmentBufferingRef = useRef(false);
  const draggingRef = useRef(false);
  const qualitySwitchRef = useRef<{
    time: number;
    resume: boolean;
  } | null>(null);
  const telemetrySessionRef = useRef(telemetrySessionId());
  const masterLoadStartedAtRef = useRef(performance.now());
  const gradedLoadStartedAtRef = useRef(performance.now());
  const masterFirstFrameWaitRef = useRef<number | null>(null);
  const gradedFirstFrameWaitRef = useRef<number | null>(null);
  const bufferingEventsRef = useRef(0);
  const [playbackStatus, setPlaybackStatus] =
    useState<PlaybackStatus>(mediaKind === "video" ? "loading" : "empty");
  const [playbackError, setPlaybackError] = useState("");
  const [gradedReadyKeys, setGradedReadyKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const activeGradedSegment = segmentAtTime(
    gradedPlaybackSegments,
    currentTime,
    duration,
  );
  const visibleGradedSegments = playbackSegmentWindow(
    gradedPlaybackSegments,
    currentTime,
    duration,
    isLooping,
  );
  const gradedMediaReady = Boolean(
    activeGradedSegment &&
      gradedReadyKeys.has(activeGradedSegment.cache_key),
  );
  const gradedPlaybackReady =
    Boolean(activeGradedSegment) && gradedMediaReady;
  const canPlay =
    mediaKind === "video" &&
    duration > 0 &&
    Boolean(source);
  const stillTolerance = Math.max(0.05, 0.55 / Math.max(1, fps));
  const exactStillVisible =
    !isPlaying &&
    previewTime !== undefined &&
    Math.abs(previewTime - currentTime) <= stillTolerance &&
    Boolean(gradedSource && originalSource);

  const mediaStyle = {
    "--pan-x": "0%",
    "--pan-scale": "1",
  } as CSSProperties;

  const syncGradedVideo = (time = mediaRef.current?.currentTime ?? 0) => {
    const master = mediaRef.current;
    const segment = segmentAtTime(gradedPlaybackSegments, time, duration);
    const graded = segment
      ? gradedVideoRefs.current.get(segment.cache_key)
      : undefined;
    if (!segment || !graded || !master || !Number.isFinite(time)) return;
    if (graded.readyState === HTMLMediaElement.HAVE_NOTHING) return;
    const switchedSegment = activeGradedKeyRef.current !== segment.cache_key;
    if (switchedSegment) {
      for (const [cacheKey, video] of gradedVideoRefs.current) {
        if (cacheKey !== segment.cache_key) video.pause();
      }
      activeGradedKeyRef.current = segment.cache_key;
    }
    const localTime = Math.max(
      0,
      Math.min(
        time - segment.start_seconds,
        Math.max(0, segment.end_seconds - segment.start_seconds - 0.001),
      ),
    );
    const tolerance = Math.max(0.06, 1.5 / Math.max(1, fps));
    if (Math.abs(graded.currentTime - localTime) > tolerance) {
      graded.currentTime = localTime;
    }
    if (
      switchedSegment &&
      !master.paused &&
      graded.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
    ) {
      void graded.play().catch(() => {
        master.pause();
        setPlaybackStatus("buffering");
        onPlaybackChange(false);
      });
    }
  };

  useEffect(() => {
    setPlaybackError("");
    setPlaybackStatus(mediaKind === "video" ? "loading" : "empty");
  }, [gradedPlaybackGroupKey, mediaKind, source]);

  useEffect(() => {
    telemetrySessionRef.current = telemetrySessionId();
    masterLoadStartedAtRef.current = performance.now();
    gradedLoadStartedAtRef.current = performance.now();
    masterFirstFrameWaitRef.current = null;
    gradedFirstFrameWaitRef.current = null;
    bufferingEventsRef.current = 0;
  }, [mediaKind, source]);

  useEffect(() => {
    setGradedReadyKeys(new Set());
    activeGradedKeyRef.current = null;
    gradedLoadStartedAtRef.current = performance.now();
    gradedFirstFrameWaitRef.current = null;
  }, [gradedPlaybackGroupKey]);

  useEffect(() => {
    if (
      mediaKind !== "video" ||
      !activeGradedSegment ||
      !gradedPlaybackReady
    ) {
      return;
    }
    const emit = () => {
      const master = mediaRef.current;
      const graded = gradedVideoRefs.current.get(
        activeGradedSegment.cache_key,
      );
      if (!master || !graded) return;
      const masterFrames = playbackFrameCounts(master);
      const gradedFrames = playbackFrameCounts(graded);
      const firstFrameWaits = [
        masterFirstFrameWaitRef.current,
        gradedFirstFrameWaitRef.current,
      ].filter((value): value is number => value !== null);
      onPlaybackTelemetry({
        session_id: telemetrySessionRef.current,
        cache_key: activeGradedSegment.cache_key,
        profile: previewProfile,
        first_frame_wait_ms:
          firstFrameWaits.length > 0 ? Math.max(...firstFrameWaits) : null,
        total_video_frames: masterFrames.total + gradedFrames.total,
        dropped_video_frames:
          masterFrames.dropped + gradedFrames.dropped,
        sync_error_ms:
          Math.abs(
            master.currentTime -
              (activeGradedSegment.start_seconds + graded.currentTime),
          ) * 1000,
        buffering_events: bufferingEventsRef.current,
        master_ready_state: master.readyState,
        graded_ready_state: graded.readyState,
        playing: !master.paused && !master.ended,
      });
    };
    const initialTimer = window.setTimeout(emit, 250);
    const interval = isPlaying ? window.setInterval(emit, 1500) : null;
    return () => {
      window.clearTimeout(initialTimer);
      if (interval !== null) window.clearInterval(interval);
    };
  }, [
    activeGradedSegment,
    gradedPlaybackReady,
    isPlaying,
    mediaKind,
    mediaRef,
    onPlaybackTelemetry,
    previewProfile,
  ]);

  useEffect(() => {
    const master = mediaRef.current;
    if (!master || mediaKind !== "video") return;
    master.muted = isMuted;
    master.loop = isLooping;
    for (const graded of gradedVideoRefs.current.values()) {
      graded.muted = true;
      graded.loop = false;
    }
  }, [isLooping, isMuted, mediaKind, mediaRef]);

  useEffect(() => {
    const media = mediaRef.current;
    if (!media || mediaKind !== "video") return;
    let frameCallback: number | null = null;
    let animationFrame: number | null = null;

    const emitFrame = (mediaTime: number) => {
      const segment = segmentAtTime(
        gradedPlaybackSegments,
        mediaTime,
        duration,
      );
      if (
        !segment ||
        !gradedReadyKeys.has(segment.cache_key) ||
        !gradedVideoRefs.current.has(segment.cache_key)
      ) {
        if (!media.paused) {
          segmentBufferingRef.current = true;
          bufferingEventsRef.current += 1;
          setPlaybackStatus("buffering");
          media.pause();
        }
        onMediaTimeChange(mediaTime);
        return;
      }
      syncGradedVideo(mediaTime);
      onMediaTimeChange(mediaTime);
    };
    const schedule = () => {
      if (media.paused || media.ended) return;
      if (typeof media.requestVideoFrameCallback === "function") {
        frameCallback = media.requestVideoFrameCallback((_now, metadata) => {
          emitFrame(metadata.mediaTime);
          schedule();
        });
      } else {
        animationFrame = window.requestAnimationFrame(() => {
          emitFrame(media.currentTime);
          schedule();
        });
      }
    };
    const start = () => {
      if (frameCallback === null && animationFrame === null) schedule();
    };
    const stop = () => {
      if (
        frameCallback !== null &&
        typeof media.cancelVideoFrameCallback === "function"
      ) {
        media.cancelVideoFrameCallback(frameCallback);
      }
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
      frameCallback = null;
      animationFrame = null;
      emitFrame(media.currentTime);
    };
    const restartAfterSeek = () => {
      stop();
      if (!media.paused && !media.ended) start();
    };

    media.addEventListener("play", start);
    media.addEventListener("pause", stop);
    media.addEventListener("seeked", restartAfterSeek);
    if (!media.paused) start();
    return () => {
      media.removeEventListener("play", start);
      media.removeEventListener("pause", stop);
      media.removeEventListener("seeked", restartAfterSeek);
      if (
        frameCallback !== null &&
        typeof media.cancelVideoFrameCallback === "function"
      ) {
        media.cancelVideoFrameCallback(frameCallback);
      }
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
    };
  }, [
    duration,
    fps,
    gradedPlaybackSegments,
    gradedReadyKeys,
    mediaKind,
    mediaRef,
    onMediaTimeChange,
    onPlaybackChange,
    source,
  ]);

  const updateCompare = (clientX: number) => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return;
    const next = ((clientX - rect.left) / rect.width) * 100;
    onCompareChange(Math.max(2, Math.min(98, next)));
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    updateCompare(event.clientX);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (draggingRef.current) updateCompare(event.clientX);
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const rememberProfileSwitch = () => {
    const master = mediaRef.current;
    qualitySwitchRef.current = {
      time: master?.currentTime ?? currentTime,
      resume: Boolean(
        isPlaying || (master && !master.paused && !master.ended),
      ),
    };
  };

  const restoreProfileSwitch = () => {
    const pending = qualitySwitchRef.current;
    const master = mediaRef.current;
    const segment = segmentAtTime(
      gradedPlaybackSegments,
      pending?.time ?? currentTime,
      duration,
    );
    const graded = segment
      ? gradedVideoRefs.current.get(segment.cache_key)
      : undefined;
    if (
      !pending ||
      !master ||
      !graded ||
      !segment ||
      !gradedPlaybackBufferReady ||
      master.readyState < HTMLMediaElement.HAVE_FUTURE_DATA ||
      graded.readyState < HTMLMediaElement.HAVE_FUTURE_DATA
    ) {
      return;
    }
    const durationLimit = Number.isFinite(master.duration)
      ? Math.min(master.duration, duration)
      : duration;
    const target = Math.max(
      0,
      Math.min(pending.time, Math.max(0, durationLimit - 0.001)),
    );
    master.currentTime = target;
    graded.currentTime = Math.max(0, target - segment.start_seconds);
    onMediaTimeChange(target);
    qualitySwitchRef.current = null;
    if (pending.resume) {
      void master.play().catch((error) => {
        const message =
          error instanceof Error ? error.message : "浏览器拒绝恢复播放";
        setPlaybackStatus("error");
        setPlaybackError(message);
        onPlaybackChange(false);
        onPlaybackError(message);
      });
    }
  };

  const handleMasterPlay = () => {
    const master = mediaRef.current;
    const segment = segmentAtTime(
      gradedPlaybackSegments,
      master?.currentTime ?? currentTime,
      duration,
    );
    const graded = segment
      ? gradedVideoRefs.current.get(segment.cache_key)
      : undefined;
    if (
      !master ||
      !graded ||
      !segment ||
      !gradedPlaybackBufferReady ||
      (!gradedReadyKeys.has(segment.cache_key) &&
        graded.readyState < HTMLMediaElement.HAVE_FUTURE_DATA)
    ) {
      segmentBufferingRef.current = true;
      master?.pause();
      setPlaybackStatus("loading");
      return;
    }
    activeGradedKeyRef.current = segment.cache_key;
    const localTime = Math.max(
      0,
      master.currentTime - segment.start_seconds,
    );
    const tolerance = Math.max(0.06, 1.5 / Math.max(1, fps));
    if (Math.abs(graded.currentTime - localTime) > tolerance) {
      graded.currentTime = localTime;
    }
    void graded.play().catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      master.pause();
      setPlaybackStatus("error");
      setPlaybackError("真实调色视频无法同步播放");
      onPlaybackChange(false);
      if (previewProfile.codec === "hevc") rememberProfileSwitch();
      onPlaybackError("真实调色视频无法同步播放");
    });
    segmentBufferingRef.current = false;
    setPlaybackError("");
    setPlaybackStatus("playing");
    onPlaybackChange(true);
  };

  const handleQualityChange = (quality: PreviewQualityPreference) => {
    if (quality === previewQualityPreference) return;
    rememberProfileSwitch();
    onPreviewQualityChange(quality);
  };

  const handleEncodingChange = (
    preference: PreviewEncodingPreference,
  ) => {
    if (preference === previewEncodingPreference) return;
    rememberProfileSwitch();
    onPreviewEncodingChange(preference);
  };

  const handleMasterLoadedMetadata = (media: HTMLVideoElement) => {
    const requestedTime = qualitySwitchRef.current?.time ?? currentTime;
    const maximumTime = Number.isFinite(media.duration)
      ? Math.max(0, media.duration - 0.001)
      : requestedTime;
    const targetTime = Math.max(0, Math.min(requestedTime, maximumTime));
    if (Math.abs(media.currentTime - targetTime) > 0.001) {
      media.currentTime = targetTime;
    }
    setPlaybackStatus("ready");
    onMediaTimeChange(targetTime);
    syncGradedVideo(targetTime);
  };

  const handleMasterCanPlay = () => {
    setPlaybackStatus(isPlaying ? "playing" : "ready");
    window.setTimeout(restoreProfileSwitch, 0);
  };

  const handleMasterPause = () => {
    for (const graded of gradedVideoRefs.current.values()) {
      graded.pause();
    }
    syncGradedVideo();
    if (segmentBufferingRef.current) {
      setPlaybackStatus("buffering");
    } else if (
      playbackStatus !== "error" &&
      playbackStatus !== "unsupported"
    ) {
      setPlaybackStatus("ready");
    }
  };

  const handleMediaError = () => {
    const master = mediaRef.current;
    if (!master) return;
    const failure = mediaErrorMessage(master);
    if (previewProfile.codec === "hevc") {
      rememberProfileSwitch();
    } else {
      qualitySwitchRef.current = null;
    }
    setPlaybackStatus(failure.status);
    setPlaybackError(failure.message);
    onPlaybackChange(false);
    onPlaybackError(failure.message);
  };

  const modeLabel = statusLabel(playbackStatus, {
    usesBrowserProxy,
    previewQuality,
    previewProfile,
    exactStillVisible,
    previewLoading: isPreviewLoading,
    gradedPlaybackReady,
    gradedPlaybackRendering: isGradedPlaybackRendering,
    gradedPlaybackProgress,
    gradedPlaybackBufferedAhead,
  });

  return (
    <section className="preview-shell">
      <div
        ref={frameRef}
        className={`preview-frame ${isPlaying ? "is-playing" : ""} status-${playbackStatus}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={() => {
          draggingRef.current = false;
        }}
      >
        <div className="preview-media graded-media">
          {mediaKind === "video" ? (
            <>
              {visibleGradedSegments.map((segment) => {
                const active =
                  activeGradedSegment?.cache_key === segment.cache_key;
                return (
                  <video
                    key={segment.cache_key}
                    ref={(video) => {
                      if (video) {
                        gradedVideoRefs.current.set(segment.cache_key, video);
                      } else {
                        gradedVideoRefs.current.delete(segment.cache_key);
                      }
                    }}
                    className={`landscape-media playback-media graded-segment-media ${
                      active ? "is-active" : "is-standby"
                    }`}
                    src={segment.url}
                    muted
                    playsInline
                    preload="auto"
                    aria-hidden="true"
                    style={mediaStyle}
                    onLoadStart={() => {
                      gradedLoadStartedAtRef.current = performance.now();
                      gradedFirstFrameWaitRef.current = null;
                    }}
                    onLoadedMetadata={(event) => {
                      const requestedTime =
                        qualitySwitchRef.current?.time ?? currentTime;
                      event.currentTarget.currentTime = active
                        ? Math.max(0, requestedTime - segment.start_seconds)
                        : 0;
                    }}
                    onLoadedData={() => {
                      if (gradedFirstFrameWaitRef.current === null) {
                        gradedFirstFrameWaitRef.current =
                          performance.now() - gradedLoadStartedAtRef.current;
                      }
                    }}
                    onCanPlay={(event) => {
                      const graded = event.currentTarget;
                      setGradedReadyKeys((current) => {
                        if (current.has(segment.cache_key)) return current;
                        const next = new Set(current);
                        next.add(segment.cache_key);
                        return next;
                      });
                      const master = mediaRef.current;
                      const segmentIsCurrent = Boolean(
                        master &&
                          segmentAtTime(
                            gradedPlaybackSegments,
                            master.currentTime,
                            duration,
                          )?.cache_key === segment.cache_key,
                      );
                      if (segmentIsCurrent) {
                        syncGradedVideo();
                      }
                      if (
                        segmentIsCurrent &&
                        segmentBufferingRef.current &&
                        gradedPlaybackBufferReady &&
                        master?.paused
                      ) {
                        segmentBufferingRef.current = false;
                        void master.play().catch(() => {
                          setPlaybackStatus("ready");
                          onPlaybackChange(false);
                        });
                      } else if (segmentIsCurrent && master?.paused) {
                        setPlaybackStatus("ready");
                      }
                      window.setTimeout(restoreProfileSwitch, 0);
                      if (
                        segmentIsCurrent &&
                        master &&
                        !master.paused &&
                        !master.ended
                      ) {
                        void graded.play().catch((error) => {
                          if (
                            error instanceof DOMException &&
                            error.name === "AbortError"
                          ) {
                            return;
                          }
                          master.pause();
                          setPlaybackStatus("error");
                          setPlaybackError("真实调色视频无法同步播放");
                          onPlaybackChange(false);
                          if (previewProfile.codec === "hevc") {
                            rememberProfileSwitch();
                          }
                          onPlaybackError("真实调色视频无法同步播放");
                        });
                      }
                    }}
                    onWaiting={() => {
                      if (!active) return;
                      bufferingEventsRef.current += 1;
                      segmentBufferingRef.current = true;
                      setPlaybackStatus("buffering");
                      mediaRef.current?.pause();
                    }}
                    onEnded={() => {
                      if (!active) return;
                      const masterTime =
                        mediaRef.current?.currentTime ?? segment.end_seconds;
                      onMediaTimeChange(masterTime);
                      syncGradedVideo(masterTime);
                    }}
                    onError={() => {
                      setGradedReadyKeys((current) => {
                        const next = new Set(current);
                        next.delete(segment.cache_key);
                        return next;
                      });
                      if (previewProfile.codec === "hevc") {
                        rememberProfileSwitch();
                      }
                      setPlaybackStatus("error");
                      setPlaybackError("真实调色视频加载失败");
                      onPlaybackChange(false);
                      onPlaybackError("真实调色视频加载失败");
                    }}
                  />
                );
              })}
              {!activeGradedSegment && !exactStillVisible && (
                <div className="true-preview-pending">
                  {isGradedPlaybackRendering
                    ? `正在生成当前 4 秒真实调色片段 ${Math.round(gradedPlaybackProgress)}%`
                    : "等待当前真实调色片段"}
                </div>
              )}
              {exactStillVisible && gradedSource && (
                <img
                  className="landscape-media exact-preview"
                  src={gradedSource}
                  alt="当前时间的精确调色单帧"
                  draggable={false}
                  style={mediaStyle}
                />
              )}
            </>
          ) : (
            <img
              className="landscape-media"
              src={gradedSource ?? source}
              alt="ColorGraph 风景代表帧"
              draggable={false}
              style={mediaStyle}
            />
          )}
        </div>

        <div
          className="preview-media original-media"
          style={{ clipPath: `inset(0 ${100 - comparePosition}% 0 0)` }}
        >
          {mediaKind === "video" ? (
            <>
              <video
                ref={mediaRef}
                className="landscape-media playback-media"
                src={source}
                muted={isMuted}
                loop={isLooping}
                playsInline
                preload="auto"
                style={mediaStyle}
                onLoadStart={() => {
                  masterLoadStartedAtRef.current = performance.now();
                  masterFirstFrameWaitRef.current = null;
                  setPlaybackStatus("loading");
                }}
                onLoadedMetadata={(event) =>
                  handleMasterLoadedMetadata(event.currentTarget)
                }
                onLoadedData={() => {
                  if (masterFirstFrameWaitRef.current === null) {
                    masterFirstFrameWaitRef.current =
                      performance.now() - masterLoadStartedAtRef.current;
                  }
                }}
                onCanPlay={handleMasterCanPlay}
                onPlaying={() => {
                  setPlaybackStatus("playing");
                  syncGradedVideo();
                  const segment = segmentAtTime(
                    gradedPlaybackSegments,
                    mediaRef.current?.currentTime ?? currentTime,
                    duration,
                  );
                  const graded = segment
                    ? gradedVideoRefs.current.get(segment.cache_key)
                    : undefined;
                  if (graded?.paused) void graded.play().catch(() => undefined);
                }}
                onWaiting={() => {
                  bufferingEventsRef.current += 1;
                  setPlaybackStatus("buffering");
                  for (const graded of gradedVideoRefs.current.values()) {
                    graded.pause();
                  }
                }}
                onSeeking={(event) =>
                  onMediaTimeChange(event.currentTarget.currentTime)
                }
                onSeeked={(event) => {
                  onMediaTimeChange(event.currentTarget.currentTime);
                  syncGradedVideo(event.currentTarget.currentTime);
                }}
                onTimeUpdate={(event) => {
                  const mediaTime = event.currentTarget.currentTime;
                  onMediaTimeChange(mediaTime);
                  syncGradedVideo(mediaTime);
                }}
                onPlay={handleMasterPlay}
                onPause={handleMasterPause}
                onEnded={() => {
                  segmentBufferingRef.current = false;
                  handleMasterPause();
                  onPlaybackChange(false);
                }}
                onError={handleMediaError}
              />
              {exactStillVisible && originalSource && (
                <img
                  className="landscape-media exact-preview"
                  src={originalSource}
                  alt="当前时间的原片单帧"
                  draggable={false}
                  style={mediaStyle}
                />
              )}
            </>
          ) : (
            <img
              className="landscape-media"
              src={originalSource ?? source}
              alt="ColorGraph 风景原片代表帧"
              draggable={false}
              style={mediaStyle}
            />
          )}
        </div>

        <div
          className="compare-divider"
          style={{ left: `${comparePosition}%` }}
        >
          <div className="compare-handle" aria-label="拖动比较原片和调色结果">
            <span />
            <span />
          </div>
        </div>

        <div className="preview-label preview-label-original">原片</div>
        <div className="preview-label preview-label-graded">COLORGRAPH</div>

        {mask !== "none" && (
          <div className={`semantic-mask mask-${mask}`} aria-hidden="true">
            {isPlaying ? (
              <div className="mask-unavailable">
                连续播放时暂停逐帧蒙版
              </div>
            ) : maskSource ? (
              <img className="real-mask-image" src={maskSource} alt="" />
            ) : (
              <div className="mask-unavailable">
                尚未生成该蒙版，请点击“AI 分析”
              </div>
            )}
            <div className="mask-tag">
              <Focus size={12} />
              {mask === "sky" && "天空"}
              {mask === "vegetation" && "植被"}
              {mask === "water" && "水面"}
              {mask === "depth" && "深度 · 远景"}
              {isPlaying
                ? " · 播放暂停"
                : maskSource
                  ? " · 逐帧模型蒙版"
                  : " · 未生成"}
            </div>
          </div>
        )}

        <div className="preview-top-overlay">
          <div>
            <span className="live-dot" />
            {shotLabel}
          </div>
          <div className={`media-state state-${playbackStatus}`}>
            {(playbackStatus === "loading" ||
              playbackStatus === "buffering") && (
              <LoaderCircle size={11} className="status-spinner" />
            )}
            {(playbackStatus === "error" ||
              playbackStatus === "unsupported") && (
              <AlertTriangle size={11} />
            )}
            {modeLabel}
          </div>
          <span>
            {resolution} · {fps.toFixed(2)} FPS
          </span>
        </div>

        {playbackError && (
          <div className="playback-error" role="status">
            <AlertTriangle size={14} />
            <span>{playbackError}</span>
          </div>
        )}
      </div>

      <div className="preview-controls">
        <div className="playback-controls">
          <button
            type="button"
            aria-label={isMuted ? "取消静音" : "静音"}
            aria-pressed={isMuted}
            disabled={!canPlay}
            title={isMuted ? "当前静音" : "当前有声"}
            onClick={onToggleMute}
          >
            {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
          <button
            className="play-button"
            type="button"
            aria-label={isPlaying ? "暂停" : "播放"}
            disabled={!canPlay}
            title={
              isPlaying
                ? "暂停"
                : gradedPlaybackReady && gradedPlaybackBufferReady
                  ? "播放真实调色视频"
                  : "点击后等待真实调色首段完成并自动播放"
            }
            onClick={() => {
              if (isPlaying) {
                segmentBufferingRef.current = false;
              }
              onTogglePlay();
            }}
          >
            {isPlaying ? (
              <Pause size={15} fill="currentColor" />
            ) : (
              <Play size={15} fill="currentColor" />
            )}
          </button>
          <button
            type="button"
            aria-label={isLooping ? "关闭循环" : "开启循环"}
            aria-pressed={isLooping}
            disabled={!canPlay}
            className={isLooping ? "is-active" : ""}
            title={isLooping ? "循环播放已开启" : "循环播放已关闭"}
            onClick={onToggleLoop}
          >
            <Repeat2 size={14} />
          </button>
          <span className="timecode">
            {formatTimecode(currentTime, fps)}
            <i>/</i>
            {formatTimecode(duration, fps)}
          </span>
        </div>

        <div className="viewer-controls">
          <div className="compare-readout">
            <span className="compare-swatch raw" />
            原片
            <span className="compare-swatch graded" />
            调色
          </div>
          <div className="control-divider" />
          <div className="quality-menu">
            <span>预览</span>
            <select
              aria-label="选择播放清晰度"
              value={previewQualityPreference}
              disabled={!previewQualityEnabled}
              onChange={(event) =>
                handleQualityChange(
                  event.target.value as PreviewQualityPreference,
                )
              }
            >
              <option value="auto">自动 · {previewQuality}</option>
              {previewQualityOptions.map((quality) => (
                <option key={quality} value={quality}>
                  {quality === "2160p" ? "2160p / 4K" : quality}
                </option>
              ))}
            </select>
            <ChevronDown size={11} />
          </div>
          <div className="encoding-menu">
            <span>编码</span>
            <select
              aria-label="选择播放编码"
              value={previewEncodingPreference}
              disabled={!previewQualityEnabled}
              onChange={(event) =>
                handleEncodingChange(
                  event.target.value as PreviewEncodingPreference,
                )
              }
            >
              <option value="auto">自动</option>
              <option value="hevc-main10">HEVC 10-bit</option>
              <option value="h264">H.264 8-bit</option>
            </select>
            <ChevronDown size={11} />
          </div>
          <div
            className={`preview-profile-readout codec-${previewProfile.codec}`}
            title={`${previewCapabilityMessage}。10-bit 仅描述代理编码与解码输入，不代表端到端 10-bit 显示。播放首帧、码率、丢帧、CPU/GPU 与双路同步会按档位记录。`}
            role="status"
          >
            <strong>
              {previewProfile.codec === "hevc"
                ? "HEVC Main10"
                : "H.264 High"}
            </strong>
            <span>
              {previewProfile.bit_depth}-bit · {previewProfile.width}×
              {previewProfile.height}
            </span>
          </div>
          <div className="mask-menu">
            <Eye size={14} />
            <select
              aria-label="选择蒙版预览"
              value={mask}
              onChange={(event) =>
                onMaskChange(event.target.value as MaskKind)
              }
            >
              <option value="none">蒙版：关闭</option>
              <option value="sky">天空蒙版</option>
              <option value="vegetation">植被蒙版</option>
              <option value="water">水面蒙版</option>
              <option value="depth">深度蒙版</option>
            </select>
            <ChevronDown size={11} />
          </div>
          <button
            className="viewer-grade-button"
            type="button"
            aria-label="显示调色控件"
            disabled
            title="请使用右侧节点参数"
          >
            <SlidersHorizontal size={14} />
          </button>
          <button
            type="button"
            aria-label="全屏预览"
            onClick={() => frameRef.current?.requestFullscreen?.()}
          >
            <Maximize2 size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}
