import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import { preview as startPreview } from "vite";

const artifactBody = Buffer.from("0123456789");
const artifactEtag = '"sha256-test"';
const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const backendRequests = [];

function setArtifactHeaders(response, contentLength) {
  response.setHeader("Accept-Ranges", "bytes");
  response.setHeader("Cache-Control", "private, max-age=60");
  response.setHeader("Content-Length", String(contentLength));
  response.setHeader("Content-Type", "application/octet-stream");
  response.setHeader("ETag", artifactEtag);
  response.setHeader("X-Content-Type-Options", "nosniff");
}

const backend = createServer((request, response) => {
  backendRequests.push(`${request.method} ${request.url}`);
  if (request.url === "/api/probe") {
    const body = Buffer.from(JSON.stringify({ ok: true, host: request.headers.host }));
    response.writeHead(200, {
      "Content-Type": "application/json",
      "Content-Length": String(body.length),
    });
    response.end(body);
    return;
  }

  if (request.url !== "/artifacts/token") {
    response.writeHead(404, { "Content-Type": "text/plain" }).end(request.url);
    return;
  }

  if (request.headers["if-none-match"] === artifactEtag) {
    response.writeHead(304, { ETag: artifactEtag }).end();
    return;
  }

  const range = request.headers.range;
  const ifRange = request.headers["if-range"];
  if (range && (!ifRange || ifRange === artifactEtag)) {
    if (range === "bytes=2-5") {
      const body = artifactBody.subarray(2, 6);
      response.statusCode = 206;
      setArtifactHeaders(response, body.length);
      response.setHeader("Content-Range", "bytes 2-5/10");
      response.end(request.method === "HEAD" ? undefined : body);
      return;
    }

    response.statusCode = 416;
    setArtifactHeaders(response, 0);
    response.setHeader("Content-Range", "bytes */10");
    response.end();
    return;
  }

  response.statusCode = 200;
  setArtifactHeaders(response, artifactBody.length);
  response.end(request.method === "HEAD" ? undefined : artifactBody);
});

await new Promise((resolve, reject) => {
  backend.once("error", reject);
  backend.listen(0, "127.0.0.1", resolve);
});

const backendAddress = backend.address();
assert.ok(backendAddress && typeof backendAddress !== "string");
const apiOrigin = `http://127.0.0.1:${backendAddress.port}`;
const proxy = {
  "/api": { target: apiOrigin, changeOrigin: false },
  "/artifacts": { target: apiOrigin, changeOrigin: false },
};
const preview = await startPreview({
  root: projectRoot,
  logLevel: "silent",
  preview: { host: "127.0.0.1", port: 0, strictPort: false, proxy },
});
const previewAddress = preview.httpServer.address();
assert.ok(previewAddress && typeof previewAddress !== "string");
const webOrigin = `http://127.0.0.1:${previewAddress.port}`;

try {
  const page = await fetch(`${webOrigin}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /<div id="root"><\/div>/);

  const api = await fetch(`${webOrigin}/api/probe`);
  const apiBody = await api.text();
  assert.equal(
    api.status,
    200,
    `Unexpected API response: ${apiBody}\nBackend requests: ${backendRequests.join(", ")}`,
  );
  assert.deepEqual(JSON.parse(apiBody), { ok: true, host: `127.0.0.1:${previewAddress.port}` });

  const partial = await fetch(`${webOrigin}/artifacts/token`, {
    headers: { Range: "bytes=2-5", "If-Range": artifactEtag },
  });
  assert.equal(partial.status, 206);
  assert.equal(partial.headers.get("content-range"), "bytes 2-5/10");
  assert.equal(partial.headers.get("accept-ranges"), "bytes");
  assert.equal(partial.headers.get("cache-control"), "private, max-age=60");
  assert.equal(partial.headers.get("content-length"), "4");
  assert.equal(partial.headers.get("content-type"), "application/octet-stream");
  assert.equal(partial.headers.get("etag"), artifactEtag);
  assert.equal(partial.headers.get("x-content-type-options"), "nosniff");
  assert.equal(await partial.text(), "2345");

  const full = await fetch(`${webOrigin}/artifacts/token`, {
    headers: { Range: "bytes=2-5", "If-Range": '"sha256-stale"' },
  });
  assert.equal(full.status, 200);
  assert.equal(await full.text(), "0123456789");

  const notModified = await fetch(`${webOrigin}/artifacts/token`, {
    headers: { "If-None-Match": artifactEtag },
  });
  assert.equal(notModified.status, 304);
  assert.equal(notModified.headers.get("etag"), artifactEtag);

  const head = await fetch(`${webOrigin}/artifacts/token`, { method: "HEAD" });
  assert.equal(head.status, 200);
  assert.equal(head.headers.get("content-length"), "10");
  assert.equal(await head.text(), "");

  const invalidRange = await fetch(`${webOrigin}/artifacts/token`, {
    headers: { Range: "bytes=99-100" },
  });
  assert.equal(invalidRange.status, 416);
  assert.equal(invalidRange.headers.get("content-range"), "bytes */10");

  console.log(`AMD gateway verified: ${webOrigin} -> ${apiOrigin}`);
} finally {
  await preview.close();
  await new Promise((resolve, reject) => backend.close((error) => (error ? reject(error) : resolve())));
}
