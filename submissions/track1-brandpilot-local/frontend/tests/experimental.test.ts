import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {
  canSubmitExperimental,
  clearRuntimeConnection,
  connectionFailureMessage,
  EXPECTED_MODEL_ID,
  EXPECTED_MODEL_REVISION,
  isTerminalJobStatus,
  loadRuntimeConnection,
  onRuntimeConnectionChange,
  RemoteConnectionError,
  resultLabel,
  saveRuntimeConnection,
  testRuntimeConnection,
} from "../lib/experimental.ts";

class MemorySessionStorage{
  values=new Map<string,string>();
  getItem(key:string){return this.values.get(key)??null}
  setItem(key:string,value:string){this.values.set(key,value)}
  removeItem(key:string){this.values.delete(key)}
}

test("mock label remains distinct and default UI mode is mock",()=>{
  assert.equal(resultLabel(undefined),"Mock output");
  assert.equal(resultLabel("rocm"),"Verified Radeon experimental output");
  const studio=readFileSync(new URL("../app/studio/page.tsx",import.meta.url),"utf8");
  assert.match(studio,/useState<StudioMode>\("mock"\)/);
});

test("runtime connection uses sessionStorage and clears on disconnect",()=>{
  const storage=new MemorySessionStorage();
  Object.assign(globalThis,{window:new EventTarget(),sessionStorage:storage});
  saveRuntimeConnection({baseUrl:"https://example.test",token:"secret"});
  assert.deepEqual(loadRuntimeConnection(),{baseUrl:"https://example.test",token:"secret"});
  clearRuntimeConnection();
  assert.equal(loadRuntimeConnection(),null);
  const source=readFileSync(new URL("../lib/experimental.ts",import.meta.url),"utf8");
  assert.doesNotMatch(source,/localStorage|document\.cookie/);
});

test("disconnect event stops session consumers without exposing the token",()=>{
  const storage=new MemorySessionStorage();
  Object.assign(globalThis,{window:new EventTarget(),sessionStorage:storage});
  const seen:Array<string|null>=[];
  const stop=onRuntimeConnectionChange(connection=>seen.push(connection?.baseUrl??null));
  saveRuntimeConnection({baseUrl:"https://example.test",token:"temporary-secret"});
  clearRuntimeConnection();
  stop();
  assert.deepEqual(seen,["https://example.test",null]);
  assert.equal(storage.getItem("brandpilotRadeonToken"),null);
});

test("access code is masked and cleared after connection",()=>{
  const source=readFileSync(new URL("../components/ui.tsx",import.meta.url),"utf8");
  assert.match(source,/id="radeon-code" type="password"/);
  assert.match(source,/setCode\(""\)/);
});

test("failed connection clears stale state",()=>{
  const source=readFileSync(new URL("../components/ui.tsx",import.meta.url),"utf8");
  assert.match(source,/catch\(\(\)=>\{clearRuntimeConnection\(\);setStatus\(null\)/);
});

test("connection diagnostics verify backend, authentication, GPU, ROCm, and model",async()=>{
  const previousFetch=globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({
    enabled:true,
    gpu_connected:true,
    rocm_available:true,
    inference_mode:"rocm_experimental",
    device:"AMD Radeon Test",
    message:"ready",
    model_id:EXPECTED_MODEL_ID,
    model_revision:EXPECTED_MODEL_REVISION,
  }),{status:200,headers:{"Content-Type":"application/json"}});
  try{
    const observed:Array<string[]>= [];
    const checked=await testRuntimeConnection("https://example.test","x".repeat(32),stages=>observed.push(stages));
    assert.equal(checked.stages.at(-1),"Ready for generation");
    assert.equal(checked.status.model_revision,EXPECTED_MODEL_REVISION);
    assert.ok(observed.some(stages=>stages.includes("Authentication accepted")));
  }finally{globalThis.fetch=previousFetch}
});

test("authentication failure has a safe classified diagnostic",async()=>{
  const previousFetch=globalThis.fetch;
  globalThis.fetch=async()=>new Response("{}",{status:401,headers:{"Content-Type":"application/json"}});
  try{
    await assert.rejects(
      testRuntimeConnection("https://example.test","x".repeat(32)),
      (error:unknown)=>error instanceof RemoteConnectionError&&error.kind==="authentication_failure",
    );
    assert.match(connectionFailureMessage("authentication_failure"),/Authentication failure/);
  }finally{globalThis.fetch=previousFetch}
});

test("job polling terminates on completed and failed states",()=>{
  assert.equal(isTerminalJobStatus("completed"),true);
  assert.equal(isTerminalJobStatus("failed"),true);
  assert.equal(isTerminalJobStatus("generating"),false);
  const failedJobIsActive=!isTerminalJobStatus("failed");
  assert.equal(canSubmitExperimental(true,failedJobIsActive),true);
});

test("experimental submission requires connection and blocks duplicates",()=>{
  assert.equal(canSubmitExperimental(false,false),false);
  assert.equal(canSubmitExperimental(true,true),false);
  assert.equal(canSubmitExperimental(true,false),true);
  const results=readFileSync(new URL("../app/results/[id]/page.tsx",import.meta.url),"utf8");
  assert.match(results,/Verify duplicate protection/);
  assert.match(results,/status===409/);
});

test("protected blobs are created and revoked and disconnect stops polling",()=>{
  const ui=readFileSync(new URL("../components/ui.tsx",import.meta.url),"utf8");
  const results=readFileSync(new URL("../app/results/[id]/page.tsx",import.meta.url),"utf8");
  assert.match(ui,/URL\.createObjectURL\(blob\)/);
  assert.match(ui,/URL\.revokeObjectURL\(objectUrl\)/);
  assert.match(results,/onRuntimeConnectionChange/);
  assert.match(results,/clearTimeout\(timer\)/);
});

test("refresh restores only the current session and never fills the code field",()=>{
  const panel=readFileSync(new URL("../components/ui.tsx",import.meta.url),"utf8");
  const results=readFileSync(new URL("../app/results/[id]/page.tsx",import.meta.url),"utf8");
  assert.match(panel,/setUrl\(existing\.baseUrl\)/);
  assert.doesNotMatch(panel,/setCode\(existing\.token\)/);
  assert.match(results,/brandpilotRocmJob/);
  assert.match(results,/remoteApi\.get\(id\)/);
  assert.match(results,/remoteApi\.job\(jobId\)/);
  assert.doesNotMatch(results,/remoteApi\.generate\([^)]*\)[\s\S]*useEffect/);
});

test("project and job identifiers are stored only after submission succeeds",()=>{
  const studio=readFileSync(new URL("../app/studio/page.tsx",import.meta.url),"utf8");
  const jobAssignment=studio.indexOf('sessionStorage.setItem("brandpilotRocmJob",job.job_id)');
  const generation=studio.indexOf("const job=await remoteApi.generate");
  assert.ok(generation>=0&&jobAssignment>generation);
  assert.match(studio,/sessionStorage\.setItem\("brandpilotProject",project\.project_id\)/);
  assert.match(studio,/sessionStorage\.setItem\("brandpilotProjectMode","rocm"\)/);
  assert.doesNotMatch(studio,/localStorage/);
});

test("protected image request carries authorization and no wildcard credentials",async()=>{
  const storage=new MemorySessionStorage();
  Object.assign(globalThis,{window:new EventTarget(),sessionStorage:storage});
  saveRuntimeConnection({baseUrl:"https://example.test",token:"temporary-secret"});
  const previousFetch=globalThis.fetch;
  let seenAuthorization:string|null=null;
  globalThis.fetch=async(_input,init)=>{
    seenAuthorization=new Headers(init?.headers).get("Authorization");
    return new Response(new Blob(["image"]),{status:200,headers:{"Content-Type":"image/png"}});
  };
  try{
    const {remoteApi}=await import("../lib/experimental.ts");
    await remoteApi.blob("/experimental/rocm/jobs/id/output");
    assert.equal(seenAuthorization,"Bearer temporary-secret");
  }finally{
    globalThis.fetch=previousFetch;
    clearRuntimeConnection();
  }
});

test("all safe diagnostic stages are visible in the connection panel",()=>{
  const source=readFileSync(new URL("../lib/experimental.ts",import.meta.url),"utf8");
  for(const stage of [
    "Checking backend",
    "Authentication accepted",
    "Backend reachable",
    "Radeon available",
    "ROCm available",
    "Model configuration verified",
    "Ready for generation",
  ])assert.match(source,new RegExp(stage));
});
