#!/usr/bin/env node

import { chromium } from "../../phase1/node_modules/playwright/index.mjs";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, dirname, basename, extname, sep } from "node:path";

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  args[process.argv[i]] = process.argv[i + 1];
}
if (!args["--app"] || !args["--output"] || args["--time"] === undefined) {
  throw new Error("usage: render_phase1_frame.mjs --app app/index.html --time seconds --mode clean|overlay --output frame.png");
}
const appPath = resolve(args["--app"]);
const appDir = dirname(appPath);
const output = resolve(args["--output"]);
const time = Number(args["--time"]);
const mode = args["--mode"] ?? "clean";
const types = {".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".png":"image/png"};
const server = createServer(async (req,res)=>{
  try {
    const raw=decodeURIComponent((req.url??"/").split("?")[0]);
    const relative=raw==="/"?basename(appPath):raw.replace(/^\/+/,"");
    const candidate=resolve(appDir,relative);
    if(candidate!==appDir && !candidate.startsWith(`${appDir}${sep}`)) throw new Error("forbidden");
    const data=await readFile(candidate);
    res.writeHead(200,{"Content-Type":types[extname(candidate)]??"application/octet-stream","Cache-Control":"no-store"});res.end(data);
  } catch {res.writeHead(404);res.end("not found");}
});
await new Promise(done=>server.listen(0,"127.0.0.1",done));
const address=server.address();
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
  await page.goto(`http://127.0.0.1:${address.port}/${encodeURIComponent(basename(appPath))}`,{waitUntil:"networkidle"});
  await page.waitForFunction(()=>window.__LIVE_SCIENCE_READY__===true&&typeof window.renderFrame==="function");
  const meta=await page.evaluate(()=>window.LIVE_SCIENCE_META);
  await page.setViewportSize({width:meta.width,height:meta.height});
  await page.evaluate(async ({time,mode})=>window.renderFrame(time,{mode}),{time,mode});
  await page.screenshot({path:output,type:"png",omitBackground:mode==="overlay",animations:"disabled",captureBeyondViewport:false});
} finally {
  await browser.close();
  await new Promise(done=>server.close(done));
}
