import { chromium } from "playwright";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const input = path.resolve(process.argv[2]);
const size = fs.statSync(input).size;

const server = http.createServer((req, res) => {
  const range = req.headers.range;
  if (!range) {
    res.writeHead(200, {
      "Accept-Ranges": "bytes",
      "Content-Length": size,
      "Content-Type": "video/webm",
    });
    fs.createReadStream(input).pipe(res);
    return;
  }
  const [startText, endText] = range.replace("bytes=", "").split("-");
  const start = Number(startText);
  const end = endText ? Number(endText) : size - 1;
  res.writeHead(206, {
    "Accept-Ranges": "bytes",
    "Content-Length": end - start + 1,
    "Content-Range": `bytes ${start}-${end}/${size}`,
    "Content-Type": "video/webm",
  });
  fs.createReadStream(input, { start, end }).pipe(res);
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const browser = await chromium.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});

try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${port}/media.webm`, { waitUntil: "domcontentloaded" });
  const result = await page.locator("video").evaluate(async (video) => {
    await video.play();
    await new Promise((resolve) => setTimeout(resolve, 750));
    const stream = video.captureStream();
    const metadata = {
      duration: video.duration,
      width: video.videoWidth,
      height: video.videoHeight,
      videoTracks: stream.getVideoTracks().length,
      audioTracks: stream.getAudioTracks().length,
      readyState: video.readyState,
    };
    video.pause();
    return metadata;
  });
  console.log(JSON.stringify({ file: input, size, ...result }, null, 2));
} finally {
  await browser.close();
  server.close();
}
