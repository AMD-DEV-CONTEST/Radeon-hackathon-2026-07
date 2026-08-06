import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve } from "node:path";

const root = resolve(import.meta.dirname);
const portArgument = process.argv.indexOf("--port");
const requestedPort = portArgument >= 0 ? Number(process.argv[portArgument + 1]) : Number(process.env.PORT);
const port = Number.isInteger(requestedPort) && requestedPort > 0 ? requestedPort : 4173;

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8"
};

const server = createServer((request, response) => {
  const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
  const requestedPath = requestUrl.pathname === "/" ? "/index.html" : requestUrl.pathname;
  const candidate = resolve(root, `.${requestedPath}`);
  const safeCandidate = candidate.startsWith(`${root}/`) && existsSync(candidate) && statSync(candidate).isFile()
    ? candidate
    : resolve(root, "index.html");

  response.setHeader("Content-Type", contentTypes[extname(safeCandidate)] ?? "application/octet-stream");
  response.setHeader("Cache-Control", "no-store");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()");
  createReadStream(safeCandidate).pipe(response);
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`ProofLaunch preview: http://127.0.0.1:${port}\n`);
});
