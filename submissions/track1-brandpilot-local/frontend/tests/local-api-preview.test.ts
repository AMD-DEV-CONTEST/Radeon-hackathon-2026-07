import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {api,API,LOCAL_API_UNAVAILABLE_MESSAGE,LocalApiUnavailableError} from "../lib/api.ts";
import {createPreviewObjectUrl,MAX_PRODUCT_IMAGE_SIZE,validateProductImage} from "../lib/local-asset-store.ts";

const read=(path:string)=>readFileSync(new URL(path,import.meta.url),"utf8");

test("mock API defaults to the loopback FastAPI service",()=>{
  assert.equal(API,"http://127.0.0.1:8000");
  const studio=read("../app/studio/page.tsx");
  const mockBranch=studio.slice(studio.indexOf('if(mode==="mock")'),studio.indexOf("if(!canSubmitExperimental"));
  assert.match(mockBranch,/api\.create\(form\)/);
  assert.match(mockBranch,/api\.upload\(project\.project_id,file\)/);
  assert.match(mockBranch,/api\.generate\(project\.project_id\)/);
  assert.doesNotMatch(mockBranch,/remoteApi|loadRuntimeConnection/);
});

test("network failures become a useful local API message",async()=>{
  const previousFetch=globalThis.fetch;
  globalThis.fetch=async()=>{throw new TypeError("Failed to fetch")};
  try{
    await assert.rejects(api.health(),(error:unknown)=>error instanceof LocalApiUnavailableError&&error.message===LOCAL_API_UNAVAILABLE_MESSAGE);
    assert.doesNotMatch(LOCAL_API_UNAVAILABLE_MESSAGE,/Failed to fetch/i);
  }finally{globalThis.fetch=previousFetch}
});

test("product image validation requires matching safe MIME types and extensions",()=>{
  assert.equal(validateProductImage({name:"bottle.jpg",type:"image/jpeg",size:2048}),null);
  assert.equal(validateProductImage({name:"bottle.jpeg",type:"image/jpeg",size:2048}),null);
  assert.equal(validateProductImage({name:"bottle.svg",type:"image/svg+xml",size:2048}),"Choose a PNG, JPEG, or WebP image.");
  assert.equal(validateProductImage({name:"bottle.html",type:"image/png",size:2048}),"The filename extension does not match the image type.");
  assert.equal(validateProductImage({name:"bottle.png",type:"image/png",size:MAX_PRODUCT_IMAGE_SIZE+1}),"Image must be 10 MB or smaller.");
});

test("preview object URLs are revoked exactly once on replace or unmount",()=>{
  const revoked:string[]=[];
  const urlApi={createObjectURL:()=>"blob:preview-1",revokeObjectURL:(url:string)=>revoked.push(url)} as Pick<typeof URL,"createObjectURL"|"revokeObjectURL">;
  const preview=createPreviewObjectUrl(new Blob(["safe image"]),urlApi);
  assert.equal(preview.url,"blob:preview-1");
  preview.revoke();preview.revoke();
  assert.deepEqual(revoked,["blob:preview-1"]);
});

test("preview component has clean loading and image-error fallbacks",()=>{
  const ui=read("../components/ui.tsx");
  assert.match(ui,/alt="Uploaded product preview" onError=\{fail\}/);
  assert.match(ui,/Preparing preview…/);
  assert.match(ui,/Preview could not be opened\. Select the image again\./);
  assert.doesNotMatch(ui,/alt=\{`Preview of/);
  assert.doesNotMatch(ui,/useMemo\(\(\)=>URL\.createObjectURL/);
});

test("IndexedDB restores the draft file and failure requires reselection",()=>{
  const store=read("../lib/local-asset-store.ts");
  const studio=read("../app/studio/page.tsx");
  assert.match(store,/indexedDB\.open/);
  assert.match(store,/blob:file\.slice/);
  assert.match(store,/filename:file\.name/);
  assert.match(store,/lastModified:file\.lastModified/);
  assert.doesNotMatch(store,/localStorage|base64|data:/i);
  assert.match(studio,/loadDraftAsset\(\)/);
  assert.match(studio,/saveDraftAsset\(next\)/);
  assert.match(studio,/clearDraftAsset\(\)/);
  assert.match(studio,/setAssetRestoreState\(assetFailed\?"reselect":restoredAsset\?"ready":"empty"\)/);
  assert.match(studio,/assetRestoreState==="reselect"\?"Reselect required":"Required"/);
});

test("mock generation remains blocked without actual image bytes",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.match(studio,/if\(!file\)\{setError\("Add a product image before generating\."\)/);
  assert.match(studio,/disabled=\{busy\|\|!file\|\|\(mode==="rocm"&&!remoteInfo\)\}/);
});

test("system status finishes with an accurate local API state",()=>{
  const ui=read("../components/ui.tsx");
  assert.match(ui,/"Checking local API"/);
  assert.match(ui,/"Local API unavailable"/);
  assert.match(ui,/Local FastAPI[\s\S]*Connected[\s\S]*Not connected/);
  assert.doesNotMatch(ui,/"API starting"/);
});
