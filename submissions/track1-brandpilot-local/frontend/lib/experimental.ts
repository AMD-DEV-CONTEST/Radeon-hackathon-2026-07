import type {CampaignResult,Project,ProjectConfig,RocmJob,SystemInfo} from "./types";

const BASE_KEY="brandpilotRadeonBase";
const TOKEN_KEY="brandpilotRadeonToken";
const CONNECTED_KEY="brandpilotRadeonConnected";
export const RUNTIME_CONNECTION_EVENT="brandpilot:runtime-connection";
export const EXPECTED_MODEL_ID="stabilityai/stable-diffusion-xl-base-1.0";
export const EXPECTED_MODEL_REVISION="462165984030d82259a11f4367a4eed129e94a7b";

export type RuntimeConnection={baseUrl:string;token:string};
export type ConnectionDiagnosticStage=
  "Checking backend"|
  "Backend reachable"|
  "Authentication accepted"|
  "Radeon available"|
  "ROCm available"|
  "Model configuration verified"|
  "Ready for generation";
export type ConnectionFailureKind=
  "network_unreachable"|
  "tls_failure"|
  "cors_failure"|
  "authentication_failure"|
  "experimental_disabled"|
  "gpu_unavailable"|
  "model_mismatch"|
  "unknown_backend_error";

export class RemoteConnectionError extends Error{
  kind:ConnectionFailureKind;
  status?:number;
  constructor(kind:ConnectionFailureKind,message:string,status?:number){
    super(message);
    this.name="RemoteConnectionError";
    this.kind=kind;
    this.status=status;
  }
}

export function connectionFailureMessage(kind:ConnectionFailureKind):string{
  const messages:Record<ConnectionFailureKind,string>={
    network_unreachable:"Network unreachable. Check the temporary endpoint and network connection.",
    tls_failure:"TLS/certificate or secure transport failure. Certificate verification remains required.",
    cors_failure:"CORS failure. The backend did not permit this local frontend origin.",
    authentication_failure:"Authentication failure. The temporary access code was rejected.",
    experimental_disabled:"Experimental Radeon mode is disabled on the backend.",
    gpu_unavailable:"GPU unavailable. The backend did not confirm an AMD Radeon ROCm device.",
    model_mismatch:"Model configuration mismatch. The validated model or revision was not reported.",
    unknown_backend_error:"Unknown backend error. Check the sanitised backend diagnostics.",
  };
  return messages[kind];
}

function notifyRuntimeConnection():void{
  if(typeof window!=="undefined")window.dispatchEvent(new Event(RUNTIME_CONNECTION_EVENT));
}

export function normalizeBackendUrl(value:string):string{
  const url=new URL(value.trim());
  const local=["localhost","127.0.0.1"].includes(url.hostname);
  if(url.protocol!=="https:"&&!(local&&url.protocol==="http:"))throw new Error("Use an HTTPS backend URL, or HTTP only for localhost.");
  url.pathname=url.pathname.replace(/\/+$/,"");
  url.search="";
  url.hash="";
  return url.toString().replace(/\/$/,"");
}

export function authHeaders(token:string,headers?:HeadersInit):Headers{
  const next=new Headers(headers);
  next.set("Authorization",`Bearer ${token}`);
  return next;
}

export function saveRuntimeConnection(connection:RuntimeConnection):void{
  sessionStorage.setItem(BASE_KEY,connection.baseUrl);
  sessionStorage.setItem(TOKEN_KEY,connection.token);
  sessionStorage.setItem(CONNECTED_KEY,"true");
  notifyRuntimeConnection();
}

export function loadRuntimeConnection():RuntimeConnection|null{
  if(typeof window==="undefined"||sessionStorage.getItem(CONNECTED_KEY)!=="true")return null;
  const baseUrl=sessionStorage.getItem(BASE_KEY);
  const token=sessionStorage.getItem(TOKEN_KEY);
  return baseUrl&&token?{baseUrl,token}:null;
}

export function clearRuntimeConnection():void{
  sessionStorage.removeItem(BASE_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(CONNECTED_KEY);
  notifyRuntimeConnection();
}

export function onRuntimeConnectionChange(callback:(connection:RuntimeConnection|null)=>void):()=>void{
  if(typeof window==="undefined")return()=>{};
  const listener=()=>callback(loadRuntimeConnection());
  window.addEventListener(RUNTIME_CONNECTION_EVENT,listener);
  return()=>window.removeEventListener(RUNTIME_CONNECTION_EVENT,listener);
}

async function remoteRequest<T>(connection:RuntimeConnection,path:string,init?:RequestInit):Promise<T>{
  let response:Response;
  try{
    response=await fetch(`${connection.baseUrl}${path}`,{...init,headers:authHeaders(connection.token,init?.headers),cache:"no-store"});
  }catch{
    throw new RemoteConnectionError("unknown_backend_error",connectionFailureMessage("unknown_backend_error"));
  }
  if(!response.ok){
    if(response.status===401||response.status===403)throw new RemoteConnectionError("authentication_failure",connectionFailureMessage("authentication_failure"),response.status);
    if(response.status===503)throw new RemoteConnectionError("experimental_disabled",connectionFailureMessage("experimental_disabled"),response.status);
    throw new RemoteConnectionError("unknown_backend_error",connectionFailureMessage("unknown_backend_error"),response.status);
  }
  return response.json();
}

async function classifyTransportFailure(baseUrl:string):Promise<RemoteConnectionError>{
  if(typeof navigator!=="undefined"&&navigator.onLine===false){
    return new RemoteConnectionError("network_unreachable",connectionFailureMessage("network_unreachable"));
  }
  try{
    await fetch(`${baseUrl}/health`,{mode:"no-cors",cache:"no-store"});
    return new RemoteConnectionError("cors_failure",connectionFailureMessage("cors_failure"));
  }catch{
    return new RemoteConnectionError("tls_failure",connectionFailureMessage("tls_failure"));
  }
}

export async function testRuntimeConnection(
  baseUrl:string,
  token:string,
  onStage?:(stages:ConnectionDiagnosticStage[])=>void,
):Promise<{connection:RuntimeConnection;status:SystemInfo;stages:ConnectionDiagnosticStage[]}>{
  const connection={baseUrl:normalizeBackendUrl(baseUrl),token};
  const stages:ConnectionDiagnosticStage[]=["Checking backend"];
  const advance=(stage:ConnectionDiagnosticStage)=>{stages.push(stage);onStage?.([...stages])};
  onStage?.([...stages]);
  let status:SystemInfo;
  try{
    status=await remoteRequest<SystemInfo>(connection,"/experimental/rocm/status");
  }catch(error){
    if(error instanceof RemoteConnectionError&&error.kind==="unknown_backend_error"&&!error.status)throw await classifyTransportFailure(connection.baseUrl);
    throw error;
  }
  advance("Backend reachable");
  advance("Authentication accepted");
  if(!status.enabled)throw new RemoteConnectionError("experimental_disabled",connectionFailureMessage("experimental_disabled"));
  if(!status.gpu_connected)throw new RemoteConnectionError("gpu_unavailable",connectionFailureMessage("gpu_unavailable"));
  advance("Radeon available");
  if(!status.rocm_available)throw new RemoteConnectionError("gpu_unavailable",connectionFailureMessage("gpu_unavailable"));
  advance("ROCm available");
  if(status.model_id!==EXPECTED_MODEL_ID||status.model_revision!==EXPECTED_MODEL_REVISION){
    throw new RemoteConnectionError("model_mismatch",connectionFailureMessage("model_mismatch"));
  }
  advance("Model configuration verified");
  advance("Ready for generation");
  return {connection,status,stages};
}

export function isTerminalJobStatus(status:string):boolean{return status==="completed"||status==="failed"}
export function canSubmitExperimental(connected:boolean,active:boolean):boolean{return connected&&!active}
export function resultLabel(mode:string|undefined):string{return mode==="rocm"?"Verified Radeon experimental output":"Mock output"}

function currentConnection():RuntimeConnection{
  const connection=loadRuntimeConnection();
  if(!connection)throw new Error("Connect to the experimental Radeon backend first.");
  return connection;
}

export const remoteApi={
  status:()=>remoteRequest<SystemInfo>(currentConnection(),"/experimental/rocm/status"),
  create:(configuration:ProjectConfig)=>remoteRequest<Project>(currentConnection(),"/projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(configuration)}),
  upload:(id:string,file:File)=>{const body=new FormData();body.append("file",file);return remoteRequest<Project["asset"]>(currentConnection(),`/projects/${id}/assets`,{method:"POST",body})},
  get:(id:string)=>remoteRequest<Project>(currentConnection(),`/projects/${id}`),
  generate:(id:string,creative_style:string,output_format:string,seed=20260725)=>remoteRequest<RocmJob>(currentConnection(),`/experimental/rocm/projects/${id}/generate`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({creative_style,output_format,seed})}),
  job:(id:string)=>remoteRequest<RocmJob>(currentConnection(),`/experimental/rocm/jobs/${id}`),
  review:(id:string,rid:string,status:string,note="")=>remoteRequest<CampaignResult>(currentConnection(),`/projects/${id}/results/${rid}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,note})}),
  blob:async(path:string)=>{const connection=currentConnection();const response=await fetch(`${connection.baseUrl}${path}`,{headers:authHeaders(connection.token),cache:"no-store"});if(!response.ok)throw new Error(`Artifact request failed (${response.status})`);return response.blob()}
};
