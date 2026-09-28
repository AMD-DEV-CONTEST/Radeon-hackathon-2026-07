"use client";

import {useEffect,useId,useRef,useState} from "react";
import Image from "next/image";
import type {CampaignResult,SystemInfo} from "@/lib/types";
import {api} from "@/lib/api";
import {updateChoiceSelection} from "@/lib/selection";
import {createPreviewObjectUrl,validateProductImage} from "@/lib/local-asset-store";
import {
  clearRuntimeConnection,
  type ConnectionDiagnosticStage,
  loadRuntimeConnection,
  remoteApi,
  saveRuntimeConnection,
  testRuntimeConnection,
} from "@/lib/experimental";
import {Icon,type IconName} from "@/components/icons";
import {Button,FormField,Surface,cx} from "@/components/primitives";

type Tone="good"|"bad"|"wait"|"info"|"neutral";

export function StatusBadge({children,tone="wait",className=""}:{children:React.ReactNode;tone?:Tone;className?:string}){
  return <span className={cx("status-badge",`status-${tone}`,className)}><span className={cx("status-dot",`status-dot-${tone}`)} aria-hidden="true"/>{children}</span>;
}

export function SectionHeading({eyebrow,title,copy,className=""}:{eyebrow:string;title:string;copy?:string;className?:string}){
  return <div className={cx("section-heading",className)}><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{copy&&<p className="lead">{copy}</p>}</div>;
}

export function ErrorAlert({message}:{message:string}){
  return <div className="alert alert-error" role="alert"><span className="alert-icon" aria-hidden="true">!</span><div><strong>Something needs attention</strong><p>{message}</p></div></div>;
}

export function LoadingState({label="Working…"}:{label?:string}){
  return <div className="loading-state" role="status"><span className="spinner" aria-hidden="true"/><span>{label}</span></div>;
}

export function EmptyState({title="Nothing here yet",children}:{title?:string;children:React.ReactNode}){
  return <Surface className="empty-state"><span className="empty-state-icon"><Icon name="layers"/></span><h2>{title}</h2><p>{children}</p></Surface>;
}

export function MockDisclosure({text="Mock concept — no Radeon generation was performed."}:{text?:string}){
  return <p className="disclosure disclosure-neutral"><Icon name="sparkles"/><span>{text}</span></p>;
}

export function UploadDropzone({file,onFile,restoreState="empty",notice=""}:{file:File|null;onFile:(file:File|null)=>void;restoreState?:"loading"|"empty"|"ready"|"reselect";notice?:string}){
  const inputId=useId();
  const [drag,setDrag]=useState(false);
  const [error,setError]=useState("");
  const pick=(next?:File)=>{
    if(!next)return;
    const validation=validateProductImage(next);
    if(validation){setError(validation);return}
    setError("");
    onFile(next);
  };
  const needsReselect=restoreState==="reselect";
  return <div className="upload-module"><div className={cx("upload-zone",drag&&"is-dragging",file&&"has-file")} onDragOver={event=>{event.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={event=>{event.preventDefault();setDrag(false);pick(event.dataTransfer.files[0])}}><input className="file-input sr-only" id={inputId} type="file" accept=".png,.jpg,.jpeg,.webp" onChange={event=>pick(event.target.files?.[0])}/>{file?<ImagePreview file={file} inputId={inputId} onClear={()=>{setError("");onFile(null)}} onInvalid={()=>{setError("Preview could not be opened. Select the image again.");onFile(null)}}/>:<><span className="upload-icon"><Icon name={needsReselect?"refresh":"upload"}/></span><div><h3>{restoreState==="loading"?"Restoring saved product image…":needsReselect?"Image must be selected again":"Bring in your product asset"}</h3><p>{needsReselect?"The saved preview was unavailable, so no asset is marked Ready.":"Drag and drop a rights-cleared image, or choose a file from this device."}</p></div><label className="button button-secondary upload-button" htmlFor={inputId}>{needsReselect?"Reselect image":"Choose image"} <Icon name="image"/></label><div className="upload-meta"><span>PNG, JPEG, WebP</span><span>Maximum 10 MB</span><span>Decoded and validated</span></div></>}</div>{notice&&<p className="upload-notice" role="status">{notice}</p>}{error&&<ErrorAlert message={error}/>}</div>;
}

export function ImagePreview({file,inputId,onClear,onInvalid}:{file:File;inputId:string;onClear:()=>void;onInvalid:()=>void}){
  const [url,setUrl]=useState("");
  const [failed,setFailed]=useState(false);
  useEffect(()=>{
    let active=true;
    const preview=createPreviewObjectUrl(file);
    Promise.resolve().then(()=>{if(active)setUrl(preview.url)});
    return()=>{active=false;preview.revoke()};
  },[file]);
  const fail=()=>{if(!failed){setFailed(true);onInvalid()}};
  return <div className="upload-preview"><div className="upload-preview-media">{url&&!failed?<Image src={url} width={720} height={480} unoptimized alt="Uploaded product preview" onError={fail}/>:<div className="upload-preview-placeholder" role="status"><Icon name="image"/><span>Preparing preview…</span></div>}<span>Ready</span></div><div className="upload-preview-copy"><p className="eyebrow">Product asset</p><h3>{file.name}</h3><p>{(file.size/1024/1024).toFixed(2)} MB · {file.type.replace("image/","").toUpperCase()}</p><div className="button-row"><label className="button button-secondary" htmlFor={inputId}>Replace <Icon name="refresh"/></label><Button type="button" variant="ghost" onClick={onClear}>Remove</Button></div></div></div>;
}

export function BrandColorPicker({colors,setColors}:{colors:string[];setColors:(colors:string[])=>void}){
  return <div className="color-grid">{colors.map((color,index)=><label key={`${index}-${color}`} className="color-control"><span className="color-swatch" style={{"--swatch":color} as React.CSSProperties}><input aria-label={`Brand color ${index+1}`} type="color" value={color} onChange={event=>setColors(colors.map((value,position)=>position===index?event.target.value:value))}/></span><span><strong>Color {index+1}</strong><small>{color.toUpperCase()}</small></span></label>)}</div>;
}

type ChoiceItem={title:string;description:string;icon:IconName;hint?:string;frame?:string};

export function AspectRatioPreview({frame="frame-square",label}:{frame?:string;label:string}){
  return <span className={cx("aspect-preview",frame)} aria-label={`${label} aspect ratio preview`} role="img"><span className="aspect-preview-safe"><span/><span/><span/></span></span>;
}

function SelectableTile({item,legend,checked,single,onChange}:{item:ChoiceItem;legend:string;checked:boolean;single:boolean;onChange:()=>void}){
  return <label className="selectable-tile"><input className="sr-only" type={single?"radio":"checkbox"} name={single?legend:undefined} checked={checked} onChange={onChange}/><span className="tile-icon"><Icon name={item.icon}/></span><span className="tile-copy"><strong>{item.title}</strong><small>{item.description}</small>{item.hint&&<em>{item.hint}</em>}</span>{item.frame&&<AspectRatioPreview frame={item.frame} label={item.title}/>}<span className="tile-check" aria-hidden="true"><Icon name="check"/></span></label>;
}

export function ChoiceGroup({legend,description,items,value,setValue,single=false,className=""}:{legend:string;description?:string;items:ChoiceItem[];value:string[];setValue:(value:string[])=>void;single?:boolean;className?:string}){
  return <fieldset className="choice-fieldset"><legend>{legend}</legend>{description&&<p>{description}</p>}<div className={cx("selection-grid",className)}>{items.map(item=><SelectableTile key={item.title} item={item} legend={legend} checked={value.includes(item.title)} single={single} onChange={()=>setValue(updateChoiceSelection(value,item.title,single))}/>)}</div></fieldset>;
}

const styles:ChoiceItem[]=[
  {title:"Luxury",description:"Editorial depth and crafted restraint.",icon:"sparkles"},
  {title:"Minimal Studio",description:"Clean light, space, and product focus.",icon:"layers"},
  {title:"Lifestyle",description:"Human context with an aspirational tone.",icon:"image"},
  {title:"Promotional Sale",description:"Direct energy for time-sensitive offers.",icon:"palette"},
];
const formats:ChoiceItem[]=[
  {title:"Instagram Square",description:"Balanced feed creative.",hint:"1:1 · 1080 × 1080",icon:"frame",frame:"frame-square"},
  {title:"Instagram Portrait",description:"Tall feed presence.",hint:"4:5 · 1080 × 1350",icon:"frame",frame:"frame-portrait"},
  {title:"Story / Reel Cover",description:"Full-screen mobile story.",hint:"9:16 · 1080 × 1920",icon:"frame",frame:"frame-story"},
  {title:"Landscape Advertisement",description:"Wide campaign placement.",hint:"1.91:1 · 1200 × 628",icon:"frame",frame:"frame-landscape"},
];

export function CreativeStyleSelector({value,setValue}:{value:string[];setValue:(value:string[])=>void}){
  return <ChoiceGroup legend="Creative style" description="Choose one visual direction. Selecting another replaces the current choice." items={styles} value={value} setValue={setValue} single/>;
}

export function OutputFormatSelector({value,setValue,single=false}:{value:string[];setValue:(value:string[])=>void;single?:boolean}){
  return <ChoiceGroup legend="Output formats" description={single?"The experimental worker accepts one format.":"Choose where the campaign concept should be framed."} items={formats} value={value} setValue={setValue} single={single} className="format-grid"/>;
}

export function SegmentedModeControl({mode,onChange}:{mode:"mock"|"rocm";onChange:(mode:"mock"|"rocm")=>void}){
  const options=[
    {value:"mock" as const,title:"Mock workspace",description:"Available now · four honest concepts",icon:"sparkles" as IconName},
    {value:"rocm" as const,title:"Experimental Radeon",description:"Temporary authenticated runtime required",icon:"cpu" as IconName},
  ];
  return <fieldset className="mode-control"><legend>Inference mode</legend><div>{options.map(option=><label key={option.value} className={cx("mode-option",option.value==="rocm"&&"mode-experimental")}><input className="sr-only" type="radio" name="mode" checked={mode===option.value} onChange={()=>onChange(option.value)}/><span className="mode-icon"><Icon name={option.icon}/></span><span><strong>{option.title}</strong><small>{option.description}</small></span><span className="mode-indicator"><Icon name="check"/></span></label>)}</div></fieldset>;
}

export function WorkflowProgress({asset,generated}:{asset:boolean;generated:boolean}){
  const steps=[
    {label:"Campaign brief",detail:"Direction captured",done:true},
    {label:"Product asset",detail:asset?"Validated and ready":"Awaiting upload",done:asset},
    {label:"Concept creation",detail:generated?"Concepts prepared":"Runs after submission",done:generated},
    {label:"Human review",detail:generated?"Decision required":"Follows creation",done:false},
  ];
  return <ol className="workflow-progress">{steps.map((step,index)=><li className={cx(step.done&&"is-complete")} key={step.label}><span className="progress-node">{step.done?<Icon name="check"/>:index+1}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div></li>)}</ol>;
}

export function SystemStatusPanel({remoteInfo=null}:{remoteInfo?:SystemInfo|null}){
  const [online,setOnline]=useState(false);
  const [checked,setChecked]=useState(false);
  const [localInfo,setLocalInfo]=useState<SystemInfo|null>(null);
  useEffect(()=>{
    let active=true;
    if(remoteInfo){Promise.resolve().then(()=>setChecked(true));return}
    Promise.all([api.health(),api.system()]).then(([,next])=>{if(active){setOnline(true);setChecked(true);setLocalInfo(next)}}).catch(()=>{if(active){setOnline(false);setChecked(true);setLocalInfo(null)}});
    return()=>{active=false};
  },[remoteInfo]);
  const info=remoteInfo||localInfo;
  const backendOnline=remoteInfo?true:online;
  const radeonReady=!!info?.gpu_connected&&!!info?.rocm_available;
  return <Surface className="dashboard-card status-panel"><header className="panel-header"><span className="panel-icon"><Icon name="cpu"/></span><div><p className="eyebrow">Environment</p><h2>System status</h2></div><StatusBadge tone={backendOnline?"good":checked?"bad":"wait"}>{backendOnline?"Local API online":checked?"Local API unavailable":"Checking local API"}</StatusBadge></header><div className="status-stack"><div><span><i className="status-dot status-dot-good"/>Frontend</span><strong>Ready</strong></div><div><span><i className={cx("status-dot",backendOnline?"status-dot-good":"status-dot-warning")}/>Local FastAPI</span><strong>{backendOnline?"Connected":"Not connected"}</strong></div><div><span><i className={cx("status-dot",radeonReady?"status-dot-good":"status-dot-neutral")}/>Radeon runtime</span><strong>{radeonReady?"Verified":"Not connected"}</strong></div><div><span><i className={cx("status-dot",info?.rocm_available?"status-dot-good":"status-dot-neutral")}/>ROCm</span><strong>{info?.rocm_available?"Available":"Inactive in mock"}</strong></div></div><p className="panel-note">{radeonReady?"Authenticated experimental runtime is ready.":backendOnline?"Mock generation is connected to the local API. Experimental Radeon remains optional.":"Start the local FastAPI backend on port 8000 to use mock generation."}</p>{radeonReady&&<details className="advanced-details"><summary>Verified runtime details</summary><dl><div><dt>Device</dt><dd>{info?.device||"Unavailable"}</dd></div><div><dt>Model</dt><dd className="breakable">{info?.model_id||"Unavailable"}</dd></div><div><dt>Revision</dt><dd className="breakable">{info?.model_revision||"Unavailable"}</dd></div></dl></details>}</Surface>;
}

export function RadeonConnectionPanel({onStatus}:{onStatus:(status:SystemInfo|null)=>void}){
  const [url,setUrl]=useState("");
  const [code,setCode]=useState("");
  const [status,setStatus]=useState<SystemInfo|null>(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [stages,setStages]=useState<ConnectionDiagnosticStage[]>([]);
  const connected=!!status?.gpu_connected&&!!status?.rocm_available;
  useEffect(()=>{
    const existing=loadRuntimeConnection();
    if(!existing)return;
    Promise.resolve().then(()=>setUrl(existing.baseUrl));
    testRuntimeConnection(existing.baseUrl,existing.token,setStages).then(checked=>{setStatus(checked.status);onStatus(checked.status)}).catch(()=>{clearRuntimeConnection();setStatus(null);setStages([]);onStatus(null)});
  },[onStatus]);
  const connect=async()=>{
    try{
      setBusy(true);setError("");
      if(code.length<32)throw new Error("Enter the temporary demo access code.");
      const checked=await testRuntimeConnection(url,code,setStages);
      saveRuntimeConnection(checked.connection);
      setCode("");setUrl(checked.connection.baseUrl);setStatus(checked.status);onStatus(checked.status);
    }catch(next){
      clearRuntimeConnection();setStatus(null);onStatus(null);setStages([]);
      setError(next instanceof Error?next.message:"Unknown backend error.");
    }finally{setBusy(false)}
  };
  const disconnect=()=>{clearRuntimeConnection();setCode("");setUrl("");setStatus(null);setStages([]);setError("");onStatus(null)};
  return <Surface className="dashboard-card connection-panel"><header className="panel-header"><span className="panel-icon panel-icon-warning"><Icon name="cpu"/></span><div><p className="eyebrow">Opt-in runtime</p><h2>Radeon connection</h2></div><StatusBadge tone={connected?"good":"neutral"}>{connected?"Verified":"Disconnected"}</StatusBadge></header><p className="panel-note">Used only for an approved temporary worker. Connection details stay in this tab&apos;s session and clear on disconnect.</p><div className="connection-fields"><FormField htmlFor="radeon-url" label="Temporary HTTPS endpoint" hint="Leave empty unless an official runtime is active."><input id="radeon-url" name="brandpilot-approved-endpoint" type="url" inputMode="url" autoComplete="new-password" data-1p-ignore="true" data-lpignore="true" spellCheck={false} value={url} onChange={event=>setUrl(event.target.value)} placeholder="Paste approved endpoint"/></FormField><FormField htmlFor="radeon-code" label="Temporary access code" hint="Masked and never compiled into the application."><input id="radeon-code" type="password" name="brandpilot-ephemeral-code" autoComplete="new-password" data-1p-ignore="true" data-lpignore="true" value={code} onChange={event=>setCode(event.target.value)} placeholder="Enter temporary code"/></FormField></div>{error&&<ErrorAlert message={error}/>}<div className="button-row"><Button type="button" variant="primary" onClick={connect} loading={busy} disabled={!url||!code}>{busy?"Checking":"Connect"}</Button><Button type="button" variant="secondary" onClick={disconnect}>Disconnect</Button><Button type="button" variant="ghost" onClick={disconnect}>Clear session</Button></div>{stages.length>0&&<ol className="connection-stages" aria-label="Connection diagnostics">{stages.map(stage=><li key={stage}><Icon name="check"/>{stage}</li>)}</ol>}{connected&&<p className="verified-runtime"><strong>{status?.device}</strong><span>{status?.model_id}</span><span className="breakable">{status?.model_revision}</span></p>}<p className="disclosure disclosure-warning"><Icon name="shield"/><span>Experimental only. No CPU fallback, mock fallback, batch run, or preservation guarantee.</span></p></Surface>;
}

export function HumanReviewPanel(){
  return <Surface className="dashboard-card"><header className="panel-header"><span className="panel-icon"><Icon name="review"/></span><div><p className="eyebrow">Required gate</p><h2>Human review</h2></div><StatusBadge>Decision pending</StatusBadge></header><p className="panel-note">Approve, reject, or request changes for every concept. Review never removes its mock or experimental disclosure.</p></Surface>;
}

export function ConfirmationDialog({open,title,children,onConfirm,onClose}:{open:boolean;title:string;children:React.ReactNode;onConfirm:()=>void;onClose:()=>void}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(open&&!ref.current?.open)ref.current?.showModal();if(!open&&ref.current?.open)ref.current.close()},[open]);
  return <dialog className="confirm-dialog" ref={ref} onClose={onClose}><span className="dialog-icon"><Icon name="review"/></span><h2>{title}</h2><p>{children}</p><div className="button-row"><Button variant="primary" onClick={onConfirm}>Confirm decision</Button><Button onClick={onClose}>Cancel</Button></div></dialog>;
}

export function RemoteImage({path,alt}:{path:string;alt:string}){
  const [src,setSrc]=useState("");
  const [error,setError]=useState("");
  useEffect(()=>{
    let active=true;let objectUrl="";
    remoteApi.blob(path).then(blob=>{if(!active)return;objectUrl=URL.createObjectURL(blob);setSrc(objectUrl)}).catch(()=>active&&setError("Protected image could not be loaded."));
    return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl)};
  },[path]);
  if(error)return <ErrorAlert message={error}/>;
  if(!src)return <LoadingState label="Loading protected image…"/>;
  return <Image className="result-image real-output" src={src} width={768} height={768} unoptimized alt={alt}/>;
}

function reviewTone(status:string):Tone{
  if(status==="approved")return "good";
  if(status==="rejected")return "bad";
  if(status==="needs_changes")return "wait";
  return "neutral";
}

export function CampaignResultCard({result,projectId,onChange}:{result:CampaignResult;projectId:string;onChange:(result:CampaignResult)=>void}){
  const [busy,setBusy]=useState("");
  const [confirm,setConfirm]=useState("");
  const [editing,setEditing]=useState(false);
  const [cardError,setCardError]=useState("");
  const [draft,setDraft]=useState({headline:result.headline,caption:result.caption,call_to_action:result.call_to_action});
  const isReal=result.mode==="rocm";
  const run=async(action:()=>Promise<CampaignResult>,label:string)=>{try{setBusy(label);setCardError("");onChange(await action())}catch(next){setCardError(next instanceof Error?next.message:"The result could not be updated.")}finally{setBusy("")}};
  const review=(status:string)=>run(()=>isReal?remoteApi.review(projectId,result.result_id,status):api.review(projectId,result.result_id,status),status);
  const saveEdit=async()=>{await run(()=>api.edit(projectId,result.result_id,draft),"Saving copy");setEditing(false)};
  const metrics:Array<[string,string|number|undefined]>= [
    ["Model",result.model_id],["Revision",result.model_revision],["Device",result.gpu_device_name],
    ["PyTorch",result.pytorch_version],["HIP / ROCm",result.hip_rocm_version],
    ["Dimensions",result.width&&result.height?`${result.width} × ${result.height}`:undefined],["Steps",result.steps],["Seed",result.seed],
    ["Model load",result.model_load_seconds!==undefined?`${result.model_load_seconds.toFixed(3)} s`:undefined],
    ["Generation",result.generation_seconds!==undefined?`${result.generation_seconds.toFixed(3)} s`:undefined],
    ["Total job",result.total_seconds!==undefined?`${result.total_seconds.toFixed(3)} s`:undefined],
    ["Peak allocated",result.peak_allocated_vram_bytes!==undefined?`${(result.peak_allocated_vram_bytes/1024**3).toFixed(2)} GiB`:undefined],
    ["Peak reserved",result.peak_reserved_vram_bytes!==undefined?`${(result.peak_reserved_vram_bytes/1024**3).toFixed(2)} GiB`:undefined],
    ["Output SHA-256",result.output_sha256],
  ];
  const visualClass=result.style.toLowerCase().replaceAll(" ","-").replace("/","");
  return <article className={cx("result-card",isReal&&"result-card-real")}><div className="result-media">{isReal&&result.image_url?<RemoteImage path={result.image_url} alt={`Experimental Radeon ${result.style} output`}/>:<div className={cx("concept-visual",`concept-${visualClass}`)} role="img" aria-label={`Mock ${result.style} campaign concept`}><span className="concept-orbit"/><span className="concept-product"><Icon name="sparkles"/></span><span className="concept-label">{result.output_format}</span></div>}<StatusBadge tone={isReal?"good":"info"} className="result-origin">{isReal?"Radeon experimental output":"Mock concept"}</StatusBadge></div><div className="result-content"><div className="result-heading"><div><p className="eyebrow">{result.output_format}</p><h2>{result.style}</h2></div><StatusBadge tone={reviewTone(result.human_review_status)}>{result.human_review_status.replace("_"," ")}</StatusBadge></div>{editing?<div className="copy-editor"><FormField htmlFor={`headline-${result.result_id}`} label="Headline"><input id={`headline-${result.result_id}`} value={draft.headline} onChange={event=>setDraft({...draft,headline:event.target.value})}/></FormField><FormField htmlFor={`caption-${result.result_id}`} label="Caption"><textarea id={`caption-${result.result_id}`} value={draft.caption} onChange={event=>setDraft({...draft,caption:event.target.value})}/></FormField><FormField htmlFor={`cta-${result.result_id}`} label="Call to action"><input id={`cta-${result.result_id}`} value={draft.call_to_action} onChange={event=>setDraft({...draft,call_to_action:event.target.value})}/></FormField><div className="button-row"><Button type="button" variant="primary" onClick={saveEdit} loading={busy==="Saving copy"}>Save copy</Button><Button type="button" variant="ghost" onClick={()=>{setDraft({headline:result.headline,caption:result.caption,call_to_action:result.call_to_action});setEditing(false)}}>Cancel</Button></div></div>:<div className="campaign-copy"><h3>{result.headline}</h3><p>{result.caption}</p><span>{result.call_to_action} <Icon name="arrow"/></span></div>}{isReal?<><p className="disclosure disclosure-success"><Icon name="shield"/><span>{result.disclosure}</span></p><details className="advanced-details result-details"><summary>Measured generation metadata</summary><dl>{metrics.filter(([,value])=>value!==undefined).map(([key,value])=><div key={key}><dt>{key}</dt><dd className="breakable">{value}</dd></div>)}</dl></details></>:<MockDisclosure/>}{cardError&&<ErrorAlert message={cardError}/>}<div className="review-toolbar" aria-label={`Review ${result.style} concept`}><Button type="button" variant="subtle" disabled={!!busy} onClick={()=>setConfirm("approved")}><Icon name="check"/>Approve</Button><Button type="button" variant="danger" disabled={!!busy} onClick={()=>setConfirm("rejected")}>Reject</Button><Button type="button" variant="secondary" disabled={!!busy} onClick={()=>setConfirm("needs_changes")}>Needs changes</Button>{!isReal&&<><Button type="button" variant="ghost" disabled={!!busy} onClick={()=>setEditing(true)}>Edit copy</Button><Button type="button" variant="ghost" disabled={!!busy} onClick={()=>run(()=>api.regenerate(projectId,result.result_id),"Regenerating")}><Icon name="refresh"/>Regenerate</Button></>}</div>{busy&&<LoadingState label={`${busy}…`}/>}</div><ConfirmationDialog open={!!confirm} title="Confirm review decision" onClose={()=>setConfirm("")} onConfirm={()=>{void review(confirm);setConfirm("")}}>Set this concept to <strong>{confirm.replace("_"," ")}</strong>?</ConfirmationDialog></article>;
}
