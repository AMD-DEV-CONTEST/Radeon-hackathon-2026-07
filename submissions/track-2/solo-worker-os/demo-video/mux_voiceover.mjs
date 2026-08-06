import { chromium } from "playwright";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const ROOT = "E:/gitproject/hackathon/solo/demo-video/final";
const VIDEO = path.join(ROOT, "solo-worker-os-live-radeon-demo-2026-08-06.webm");
const AUDIO = path.join(ROOT, "audio", "solo-worker-os-live-radeon-voiceover-en.wav");
const OUTPUT = path.join(ROOT, "solo-worker-os-live-radeon-demo-2026-08-06-en-vo.webm");
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";

function sendFile(req, res, file, contentType) {
  const size = fs.statSync(file).size;
  const range = req.headers.range;
  if (!range) {
    res.writeHead(200, {
      "Accept-Ranges": "bytes",
      "Content-Length": size,
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    });
    fs.createReadStream(file).pipe(res);
    return;
  }

  const [startText, endText] = range.replace("bytes=", "").split("-");
  const start = Number(startText);
  const end = endText ? Number(endText) : size - 1;
  res.writeHead(206, {
    "Accept-Ranges": "bytes",
    "Content-Length": end - start + 1,
    "Content-Range": `bytes ${start}-${end}/${size}`,
    "Content-Type": contentType,
    "Cache-Control": "no-store",
  });
  fs.createReadStream(file, { start, end }).pipe(res);
}

const server = http.createServer((req, res) => {
  if (req.url === "/video.webm") return sendFile(req, res, VIDEO, "video/webm");
  if (req.url === "/audio.wav") return sendFile(req, res, AUDIO, "audio/wav");
  res.writeHead(404).end();
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});

try {
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: { width: 1920, height: 1080 },
  });
  const page = await context.newPage();
  await page.goto(`http://127.0.0.1:${port}/video.webm`, { waitUntil: "domcontentloaded" });

  const downloadPromise = page.waitForEvent("download", { timeout: 120_000 });
  await page.evaluate(async ({ port }) => {
    document.body.innerHTML = `
      <style>html,body{margin:0;background:#000;overflow:hidden}video{width:1920px;height:1080px}</style>
      <video id="source-video" preload="auto" muted src="http://127.0.0.1:${port}/video.webm"></video>
      <audio id="voiceover" preload="auto" src="http://127.0.0.1:${port}/audio.wav"></audio>`;

    const video = document.querySelector("#source-video");
    const audio = document.querySelector("#voiceover");
    const waitForMetadata = (media) =>
      new Promise((resolve, reject) => {
        if (media.readyState >= 1) return resolve();
        media.addEventListener("loadedmetadata", resolve, { once: true });
        media.addEventListener("error", () => reject(media.error), { once: true });
      });
    await Promise.all([waitForMetadata(video), waitForMetadata(audio)]);

    const audioContext = new AudioContext();
    const audioSource = audioContext.createMediaElementSource(audio);
    const audioDestination = audioContext.createMediaStreamDestination();
    audioSource.connect(audioDestination);
    await audioContext.resume();

    const videoStream = video.captureStream(30);
    const stream = new MediaStream([
      ...videoStream.getVideoTracks(),
      ...audioDestination.stream.getAudioTracks(),
    ]);
    if (stream.getVideoTracks().length !== 1 || stream.getAudioTracks().length !== 1) {
      throw new Error("Expected one video track and one audio track.");
    }

    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
      ? "video/webm;codecs=vp9,opus"
      : "video/webm";
    const chunks = [];
    const recorder = new MediaRecorder(stream, {
      mimeType,
      videoBitsPerSecond: 5_000_000,
      audioBitsPerSecond: 128_000,
    });
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });

    const stopped = new Promise((resolve) => recorder.addEventListener("stop", resolve, { once: true }));
    recorder.start(1000);
    video.currentTime = 0;
    audio.currentTime = 0;
    await Promise.all([video.play(), audio.play()]);
    await new Promise((resolve) => video.addEventListener("ended", resolve, { once: true }));
    recorder.stop();
    await stopped;

    const blob = new Blob(chunks, { type: mimeType });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "solo-worker-os-live-radeon-demo-2026-08-06-en-vo.webm";
    link.click();
  }, { port });

  const download = await downloadPromise;
  await download.saveAs(OUTPUT);
  await context.close();
  console.log(OUTPUT);
} finally {
  await browser.close();
  server.close();
}
