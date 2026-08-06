import type {
  PreviewCodec,
  PreviewEncodingPreference,
  PreviewPlaybackProfile,
  PreviewQuality,
  PreviewQualityPreference,
} from "./types";

interface PreviewQualitySpec {
  maximumWidth: number;
  maximumHeight: number;
  targetFps: number;
  h264Bitrate: number;
  hevcBitrate: number;
  h264Codec: string;
  hevcCodec: string;
}

interface DecodingCapability {
  supported: boolean;
  smooth: boolean;
  powerEfficient: boolean;
  source: "media-capabilities" | "can-play-type";
}

export interface PreviewCapabilityResolution {
  profile: PreviewPlaybackProfile;
  message: string;
  hevc: DecodingCapability;
  h264: DecodingCapability;
}

export const PREVIEW_QUALITY_ORDER: PreviewQuality[] = [
  "2160p",
  "1440p",
  "1080p",
  "540p",
];

export const PREVIEW_QUALITY_SPECS: Record<
  PreviewQuality,
  PreviewQualitySpec
> = {
  "540p": {
    maximumWidth: 960,
    maximumHeight: 540,
    targetFps: 15,
    h264Bitrate: 1_500_000,
    hevcBitrate: 900_000,
    h264Codec: "avc1.64001F",
    hevcCodec: "hvc1.2.4.L93.B0",
  },
  "1080p": {
    maximumWidth: 1920,
    maximumHeight: 1080,
    targetFps: 30,
    h264Bitrate: 6_000_000,
    hevcBitrate: 3_500_000,
    h264Codec: "avc1.64002A",
    hevcCodec: "hvc1.2.4.L123.B0",
  },
  "1440p": {
    maximumWidth: 2560,
    maximumHeight: 1440,
    targetFps: 30,
    h264Bitrate: 10_000_000,
    hevcBitrate: 6_000_000,
    h264Codec: "avc1.640032",
    hevcCodec: "hvc1.2.4.L150.B0",
  },
  "2160p": {
    maximumWidth: 3840,
    maximumHeight: 2160,
    targetFps: 30,
    h264Bitrate: 18_000_000,
    hevcBitrate: 10_000_000,
    h264Codec: "avc1.640033",
    hevcCodec: "hvc1.2.4.L153.B0",
  },
};

export function scaledPreviewDimensions(
  sourceWidth: number,
  sourceHeight: number,
  quality: PreviewQuality,
): { width: number; height: number } {
  const spec = PREVIEW_QUALITY_SPECS[quality];
  const scale = Math.min(
    1,
    spec.maximumWidth / Math.max(1, sourceWidth),
    spec.maximumHeight / Math.max(1, sourceHeight),
  );
  return {
    width: Math.max(2, Math.floor((sourceWidth * scale) / 2) * 2),
    height: Math.max(2, Math.floor((sourceHeight * scale) / 2) * 2),
  };
}

export function availablePreviewQualities(
  sourceWidth: number,
  sourceHeight: number,
): PreviewQuality[] {
  const available = PREVIEW_QUALITY_ORDER.filter((quality) => {
    const spec = PREVIEW_QUALITY_SPECS[quality];
    return (
      sourceWidth >= spec.maximumWidth || sourceHeight >= spec.maximumHeight
    );
  });
  if (!available.includes("540p")) available.push("540p");
  return available;
}

export function buildPreviewPlaybackProfile(
  quality: PreviewQuality,
  codec: PreviewCodec,
  sourceWidth: number,
  sourceHeight: number,
  sourceFps: number,
): PreviewPlaybackProfile {
  const dimensions = scaledPreviewDimensions(
    sourceWidth,
    sourceHeight,
    quality,
  );
  const hevc = codec === "hevc";
  return {
    quality,
    codec,
    codec_profile: hevc ? "main10" : "high",
    bit_depth: hevc ? 10 : 8,
    pixel_format: hevc ? "yuv420p10le" : "yuv420p",
    width: dimensions.width,
    height: dimensions.height,
    fps: Math.min(
      Math.max(sourceFps, 1),
      PREVIEW_QUALITY_SPECS[quality].targetFps,
    ),
    color_range: "limited",
    color_primaries: "bt709",
    color_transfer: "bt709",
    color_matrix: "bt709",
    mov_tag: hevc ? "hvc1" : "avc1",
  };
}

function contentType(quality: PreviewQuality, codec: PreviewCodec): string {
  const spec = PREVIEW_QUALITY_SPECS[quality];
  const codecString = codec === "hevc" ? spec.hevcCodec : spec.h264Codec;
  return `video/mp4; codecs="${codecString}"`;
}

async function decodingCapability(
  quality: PreviewQuality,
  codec: PreviewCodec,
  width: number,
  height: number,
  framerate: number,
): Promise<DecodingCapability> {
  const spec = PREVIEW_QUALITY_SPECS[quality];
  const mime = contentType(quality, codec);
  const fallbackSupported =
    document.createElement("video").canPlayType(mime) !== "";
  if (!navigator.mediaCapabilities?.decodingInfo) {
    return {
      supported: fallbackSupported,
      smooth: fallbackSupported,
      powerEfficient: false,
      source: "can-play-type",
    };
  }
  try {
    const result = await navigator.mediaCapabilities.decodingInfo({
      type: "file",
      video: {
        contentType: mime,
        width,
        height,
        bitrate:
          codec === "hevc" ? spec.hevcBitrate : spec.h264Bitrate,
        framerate,
      },
    });
    return {
      supported: result.supported,
      smooth: result.smooth,
      powerEfficient: result.powerEfficient,
      source: "media-capabilities",
    };
  } catch {
    return {
      supported: fallbackSupported,
      smooth: fallbackSupported,
      powerEfficient: false,
      source: "can-play-type",
    };
  }
}

function automaticPreviewQuality(
  sourceWidth: number,
  sourceHeight: number,
): { quality: PreviewQuality; reason: string } {
  const available = availablePreviewQualities(sourceWidth, sourceHeight);
  const navigatorWithHints = navigator as Navigator & {
    deviceMemory?: number;
    connection?: {
      saveData?: boolean;
      effectiveType?: string;
      downlink?: number;
    };
  };
  const connection = navigatorWithHints.connection;
  const effectiveType = connection?.effectiveType ?? "unknown";
  const downlink = connection?.downlink;
  const deviceMemory = navigatorWithHints.deviceMemory ?? 4;
  const hardwareConcurrency = navigator.hardwareConcurrency || 4;

  if (
    connection?.saveData ||
    effectiveType === "slow-2g" ||
    effectiveType === "2g" ||
    effectiveType === "3g" ||
    (downlink !== undefined && downlink < 8)
  ) {
    return {
      quality: "540p",
      reason: connection?.saveData
        ? "省流模式启用，自动使用 540p"
        : "当前带宽提示偏低，自动使用 540p",
    };
  }
  if (
    available.includes("2160p") &&
    deviceMemory >= 8 &&
    hardwareConcurrency >= 12 &&
    downlink !== undefined &&
    downlink >= 50
  ) {
    return {
      quality: "2160p",
      reason: "设备与带宽提示均满足 4K 档位",
    };
  }
  if (
    available.includes("1440p") &&
    deviceMemory >= 8 &&
    hardwareConcurrency >= 8 &&
    downlink !== undefined &&
    downlink >= 20
  ) {
    return {
      quality: "1440p",
      reason: "设备与带宽提示满足 1440p 档位",
    };
  }
  if (available.includes("1080p")) {
    return {
      quality: "1080p",
      reason: "采用兼顾首帧等待、功耗与清晰度的 1080p 档位",
    };
  }
  return {
    quality: available[0] ?? "540p",
    reason: "按源素材尺寸选择可用档位，不进行放大",
  };
}

export async function resolvePreviewPlaybackProfile({
  quality,
  preference,
  sourceWidth,
  sourceHeight,
  sourceFps,
  forceH264,
}: {
  quality: PreviewQualityPreference;
  preference: PreviewEncodingPreference;
  sourceWidth: number;
  sourceHeight: number;
  sourceFps: number;
  forceH264: boolean;
}): Promise<PreviewCapabilityResolution> {
  const automatic = quality === "auto";
  const automaticSelection = automatic
    ? automaticPreviewQuality(sourceWidth, sourceHeight)
    : null;
  let resolvedQuality: PreviewQuality =
    automaticSelection?.quality ?? (quality === "auto" ? "1080p" : quality);
  const dimensions = scaledPreviewDimensions(
    sourceWidth,
    sourceHeight,
    resolvedQuality,
  );
  const framerate = Math.min(
    Math.max(sourceFps, 1),
    PREVIEW_QUALITY_SPECS[resolvedQuality].targetFps,
  );
  let [hevc, h264] = await Promise.all([
    decodingCapability(
      resolvedQuality,
      "hevc",
      dimensions.width,
      dimensions.height,
      framerate,
    ),
    decodingCapability(
      resolvedQuality,
      "h264",
      dimensions.width,
      dimensions.height,
      framerate,
    ),
  ]);
  if (automatic && !hevc.smooth && !h264.smooth && resolvedQuality !== "540p") {
    const available = availablePreviewQualities(sourceWidth, sourceHeight);
    const currentIndex = available.indexOf(resolvedQuality);
    resolvedQuality = available[currentIndex + 1] ?? "540p";
    const fallbackDimensions = scaledPreviewDimensions(
      sourceWidth,
      sourceHeight,
      resolvedQuality,
    );
    const fallbackFramerate = Math.min(
      Math.max(sourceFps, 1),
      PREVIEW_QUALITY_SPECS[resolvedQuality].targetFps,
    );
    [hevc, h264] = await Promise.all([
      decodingCapability(
        resolvedQuality,
        "hevc",
        fallbackDimensions.width,
        fallbackDimensions.height,
        fallbackFramerate,
      ),
      decodingCapability(
        resolvedQuality,
        "h264",
        fallbackDimensions.width,
        fallbackDimensions.height,
        fallbackFramerate,
      ),
    ]);
  }
  const connection = (
    navigator as Navigator & {
      connection?: { saveData?: boolean };
    }
  ).connection;
  const saveData = Boolean(connection?.saveData);
  const hevcUsable = hevc.supported && hevc.smooth;
  const autoPrefersHevc =
    hevcUsable &&
    (resolvedQuality === "1440p" || resolvedQuality === "2160p") &&
    (hevc.powerEfficient || saveData);
  const useHevc =
    !forceH264 &&
    ((preference === "hevc-main10" && hevcUsable) ||
      (preference === "auto" && autoPrefersHevc));
  const profile = buildPreviewPlaybackProfile(
    resolvedQuality,
    useHevc ? "hevc" : "h264",
    sourceWidth,
    sourceHeight,
    sourceFps,
  );

  let message: string;
  if (forceH264) {
    message = "HEVC 实际播放失败，已可靠回退 H.264 8-bit";
  } else if (preference === "h264") {
    message = "手动使用 H.264 8-bit 兼容档";
  } else if (preference === "hevc-main10" && !hevcUsable) {
    message = "浏览器未报告流畅 HEVC Main10，已回退 H.264 8-bit";
  } else if (useHevc) {
    message = hevc.powerEfficient
      ? "MediaCapabilities：HEVC Main10 可解码、流畅且节能"
      : "MediaCapabilities：HEVC Main10 可解码且流畅";
  } else if (!h264.supported) {
    message = "浏览器未确认 H.264 解码能力，将以实际播放结果为准";
  } else {
    message = "自动策略选择 H.264 8-bit 兼容档";
  }
  if (automatic) {
    const capabilityFallback =
      resolvedQuality !== automaticSelection?.quality
        ? `；目标档位未报告流畅解码，降至 ${resolvedQuality}`
        : "";
    message = `${automaticSelection?.reason ?? "自动档位"}${capabilityFallback}；${message}`;
  }
  return { profile, message, hevc, h264 };
}
