export class ClipRecorder {
  constructor({ video, fps, mimeType = "video/webm;codecs=vp9" }) {
    this.video = video;
    this.fps = fps;
    this.mimeType = MediaRecorder.isTypeSupported(mimeType) ? mimeType : "video/webm";
    this.stream = null;
  }

  async startPreview() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { frameRate: { ideal: this.fps, max: this.fps } },
      audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();
  }

  async recordClip({ durationMs }) {
    if (!this.stream) await this.startPreview();
    const chunks = [];
    const recorder = new MediaRecorder(this.stream, {
      mimeType: this.mimeType,
      videoBitsPerSecond: 2_500_000,
    });
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    };
    const stopped = new Promise((resolve, reject) => {
      recorder.onstop = resolve;
      recorder.onerror = () => reject(new Error("video recording failed"));
    });
    recorder.start();
    await new Promise((resolve) => window.setTimeout(resolve, durationMs));
    if (recorder.state !== "inactive") recorder.stop();
    await stopped;
    return new Blob(chunks, { type: this.mimeType });
  }

  stop() {
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop();
    }
    this.stream = null;
  }
}
