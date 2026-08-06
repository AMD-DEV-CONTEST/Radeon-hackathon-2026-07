import { useEffect, useRef, useState } from "react";
import {
  humanizeNetworkError,
  transcribeAudio,
  type AudioFormat
} from "../api";
import { SourceIcon } from "./SourceIcon";

type VoiceStatus =
  | "idle"
  | "recording"
  | "transcribing"
  | "success"
  | "permission_denied"
  | "unsupported"
  | "error";

type VoiceInputButtonProps = {
  disabled: boolean;
  onTranscript: (text: string) => void;
};

const RECORDING_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4"
];

export function VoiceInputButton({
  disabled,
  onTranscript
}: VoiceInputButtonProps) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const elapsedTimerRef = useRef<number | null>(null);
  const maxDurationTimerRef = useRef<number | null>(null);
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [message, setMessage] = useState<string>(
    "点击开始录音；转写只会填入输入框，不会自动发送。"
  );
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    return () => {
      clearTimers();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      recorderRef.current = null;
    };
  }, []);

  function clearTimers(): void {
    if (elapsedTimerRef.current != null) {
      window.clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
    if (maxDurationTimerRef.current != null) {
      window.clearTimeout(maxDurationTimerRef.current);
      maxDurationTimerRef.current = null;
    }
  }

  async function startRecording(): Promise<void> {
    if (disabled || status === "recording" || status === "transcribing") return;
    const mimeType = supportedMimeType();
    if (!navigator.mediaDevices?.getUserMedia || !mimeType) {
      setStatus("unsupported");
      setMessage("当前环境不支持浏览器录音，无法使用语音输入。");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      if (isPermissionError(error)) {
        setStatus("permission_denied");
        setMessage("录音权限被拒绝，请在浏览器设置中允许麦克风后重试。");
        return;
      }
      setStatus("error");
      setMessage("无法打开麦克风，请检查设备后重试。");
      return;
    }

    try {
      const recorder = new MediaRecorder(stream, { mimeType });
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      startedAtRef.current = Date.now();
      setElapsedMs(0);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        cleanupRecording();
        setStatus("error");
        setMessage("录音失败，请重试。");
      };
      recorder.onstop = () => {
        const durationMs = Math.max(100, Date.now() - startedAtRef.current);
        const chunks = chunksRef.current;
        cleanupRecording();
        void transcribeRecordedAudio(chunks, mimeType, durationMs);
      };
      recorder.start();
      setStatus("recording");
      setMessage("正在录音，再次点击停止。最长 15 秒。");
      elapsedTimerRef.current = window.setInterval(() => {
        setElapsedMs(Date.now() - startedAtRef.current);
      }, 250);
      maxDurationTimerRef.current = window.setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, 15_000);
    } catch {
      stream.getTracks().forEach((track) => track.stop());
      setStatus("unsupported");
      setMessage("当前环境不支持所需的录音格式。");
    }
  }

  function stopRecording(): void {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
  }

  function cleanupRecording(): void {
    clearTimers();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }

  async function transcribeRecordedAudio(
    chunks: Blob[],
    mimeType: string,
    durationMs: number
  ): Promise<void> {
    setStatus("transcribing");
    setMessage("正在转写…");
    try {
      const format = formatForMimeType(mimeType);
      if (!format) {
        setStatus("unsupported");
        setMessage("当前环境不支持浏览器录音格式。");
        return;
      }
      const blob = new Blob(chunks, { type: mimeType });
      if (blob.size === 0) throw new Error("录音内容为空。");
      const audioDataUrl = await blobToDataUrl(blob);
      const result = await transcribeAudio({
        audioDataUrl,
        format,
        durationMs
      });
      if (!result.transcript.trim()) {
        setStatus("error");
        setMessage("没有听清这段录音，请靠近麦克风再试一次。");
        return;
      }
      onTranscript(result.transcript.trim());
      setStatus("success");
      setMessage("已填入输入框，请检查内容后亲自点击“发送”。");
    } catch (error) {
      const message = humanizeNetworkError(error);
      if (/当前环境暂不支持音频转写|音频依赖|不支持音频/i.test(message)) {
        setStatus("unsupported");
        setMessage(message);
        return;
      }
      setStatus("error");
      setMessage(message);
    }
  }

  const isRecording = status === "recording";
  const statusLabel = isRecording
    ? `录音中 ${Math.ceil(elapsedMs / 1_000)} 秒`
    : status === "transcribing"
      ? "正在转写"
      : status === "success"
        ? "转写成功"
        : status === "permission_denied"
          ? "录音权限拒绝"
          : status === "unsupported"
            ? "当前环境不支持"
            : status === "error"
              ? "转写失败"
              : "可录音";

  return (
    <div className="voice-input-control">
      <button
        className={`voice-input-button ${isRecording ? "recording" : ""}`}
        type="button"
        disabled={disabled || status === "transcribing"}
        onClick={() => void (isRecording ? stopRecording() : startRecording())}
        aria-label={isRecording ? "停止录音" : "开始语音输入"}
        aria-pressed={isRecording}
      >
        <SourceIcon name="mic" size={18} />
        <span className="voice-input-label">
          {isRecording ? "停止录音" : status === "success" ? "重新录音" : "语音输入"}
        </span>
      </button>
      <span
        className={`voice-input-status voice-input-status-${status}`}
        role="status"
        aria-live="polite"
      >
        {statusLabel} · {message}
      </span>
    </div>
  );
}

function supportedMimeType(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  return (
    RECORDING_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null
  );
}

function formatForMimeType(mimeType: string): AudioFormat | null {
  const base = mimeType.split(";", 1)[0]?.toLowerCase();
  if (base === "audio/webm") return "webm";
  if (base === "audio/ogg") return "ogg";
  if (base === "audio/wav" || base === "audio/x-wav") return "wav";
  if (base === "audio/mp4") return "mp4";
  if (base === "audio/mpeg") return "mpeg";
  if (base === "audio/x-m4a") return "m4a";
  return null;
}

function isPermissionError(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === "NotAllowedError" || error.name === "PermissionDeniedError")
  );
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("录音读取失败。"));
    };
    reader.onerror = () => reject(new Error("录音读取失败。"));
    reader.readAsDataURL(blob);
  });
}
