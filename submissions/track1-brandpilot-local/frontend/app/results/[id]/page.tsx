"use client";

import {use,useEffect,useState} from "react";
import Image from "next/image";
import {Icon} from "@/components/icons";
import {Button,Surface} from "@/components/primitives";
import {api,API} from "@/lib/api";
import {clearRuntimeConnection,isTerminalJobStatus,onRuntimeConnectionChange,RemoteConnectionError,remoteApi} from "@/lib/experimental";
import type {Project,RocmJob,SystemInfo} from "@/lib/types";
import {
  CampaignResultCard,
  ErrorAlert,
  HumanReviewPanel,
  LoadingState,
  RemoteImage,
  SectionHeading,
  StatusBadge,
  SystemStatusPanel,
  WorkflowProgress,
} from "@/components/ui";

export default function Results({params}:{params:Promise<{id:string}>}){
  const {id}=use(params);
  const [project,setProject]=useState<Project|null>(null);
  const [job,setJob]=useState<RocmJob|null>(null);
  const [remoteInfo,setRemoteInfo]=useState<SystemInfo|null>(null);
  const [mode,setMode]=useState<"mock"|"rocm">("mock");
  const [error,setError]=useState("");
  const [duplicateCheck,setDuplicateCheck]=useState("");

  useEffect(()=>{
    let cancelled=false;
    let timer:ReturnType<typeof setTimeout>|undefined;
    const stopOnDisconnect=onRuntimeConnectionChange(connection=>{
      if(connection)return;
      cancelled=true;
      if(timer)clearTimeout(timer);
      setRemoteInfo(null);
      setError("Experimental Radeon connection was cleared. Polling stopped.");
    });
    const storedMode=sessionStorage.getItem("brandpilotProjectMode")==="rocm"?"rocm":"mock";
    Promise.resolve().then(()=>!cancelled&&setMode(storedMode));
    if(storedMode==="mock"){
      api.get(id).then(next=>!cancelled&&setProject(next)).catch(next=>!cancelled&&setError(next.message));
      return()=>{cancelled=true;stopOnDisconnect()};
    }
    const jobId=sessionStorage.getItem("brandpilotRocmJob");
    const loadProject=()=>remoteApi.get(id).then(next=>{if(!cancelled)setProject(next)});
    const poll=async()=>{
      if(!jobId){await loadProject();return}
      try{
        const next=await remoteApi.job(jobId);
        if(cancelled)return;
        setJob(next);
        if(next.status==="completed"){await loadProject();return}
        if(next.status==="failed"){setError(next.failure||"Experimental Radeon generation failed.");await loadProject();return}
        if(!isTerminalJobStatus(next.status))timer=setTimeout(poll,1500);
      }catch(next){
        if(cancelled)return;
        clearRuntimeConnection();
        setRemoteInfo(null);
        setError(next instanceof Error?next.message:"Remote job status failed.");
      }
    };
    Promise.all([loadProject(),remoteApi.status().then(setRemoteInfo)]).then(poll).catch(next=>{
      clearRuntimeConnection();
      setRemoteInfo(null);
      setError(next instanceof Error?next.message:"Remote connection failed.");
    });
    return()=>{cancelled=true;if(timer)clearTimeout(timer);stopOnDisconnect()};
  },[id]);

  if(error&&!project)return <div className="container state-page"><ErrorAlert message={error}/></div>;
  if(!project)return <div className="container state-page"><LoadingState label="Loading campaign…"/></div>;

  const update=(next:Project["results"][number])=>setProject({...project,results:project.results.map(result=>result.result_id===next.result_id?next:result)});
  const verifyDuplicateProtection=async()=>{
    setDuplicateCheck("Checking duplicate protection…");
    try{
      await remoteApi.generate(id,project.configuration.creative_styles[0],project.configuration.output_formats[0]);
      setDuplicateCheck("Unexpected: duplicate submission was accepted.");
    }catch(next){
      setDuplicateCheck(next instanceof RemoteConnectionError&&next.status===409
        ?"Duplicate submission rejected by the single-job worker."
        :"Duplicate check failed without a confirmed rejection.");
    }
  };
  const generated=project.results.length>0;
  const jobProgress=job?.current_step!==null&&job?.current_step!==undefined&&job?.total_steps
    ?Math.min(100,Math.round(job.current_step/job.total_steps*100))
    :job?.status==="completed"?100:8;

  return <div className="results-page">
    <header className="container page-hero results-hero">
      <SectionHeading eyebrow={mode==="rocm"?"Experimental Radeon result":"Campaign results"} title={project.configuration.product_name} copy={`${project.configuration.campaign_goal} · ${project.configuration.target_audience}`}/>
      <div className="page-hero-aside"><StatusBadge tone={mode==="rocm"?"info":"neutral"}>{mode==="rocm"?"Verified Radeon experimental workflow":"Safe local mock workflow"}</StatusBadge><p>Project <span className="mono">{id.slice(0,8)}</span></p></div>
    </header>

    <div className="container results-layout">
      {error&&<ErrorAlert message={error}/>}
      <Surface className="project-overview">
        <div className="project-asset">
          {project.asset&&(mode==="rocm"
            ?<RemoteImage path={project.asset.url} alt={`Original ${project.configuration.product_name}`}/>
            :<Image className="preview" width={720} height={480} unoptimized src={`${API}${project.asset.url}`} alt={`Original ${project.configuration.product_name}`}/>)}
          {!project.asset&&<div className="asset-placeholder"><Icon name="image" width={30} height={30}/><span>No asset attached</span></div>}
        </div>
        <div className="project-summary"><p className="eyebrow">Campaign brief</p><h2>{project.configuration.product_category}</h2><dl className="brief-list"><div><dt>Brand tone</dt><dd>{project.configuration.brand_tone}</dd></div><div><dt>Creative direction</dt><dd>{project.configuration.creative_styles.join(", ")}</dd></div><div><dt>Formats</dt><dd>{project.configuration.output_formats.join(", ")}</dd></div><div><dt>Palette</dt><dd>{project.configuration.brand_colors.join(", ")||"Not specified"}</dd></div></dl></div>
        <WorkflowProgress asset={Boolean(project.asset)} generated={generated}/>
      </Surface>

      {mode==="rocm"&&job&&<Surface className="job-card">
        <div className="job-card-head"><div><p className="eyebrow">Live GPU job</p><h2>{job.status.replaceAll("_"," ")}</h2></div><StatusBadge tone={job.status==="completed"?"good":job.status==="failed"?"bad":"info"}>{job.stage.replaceAll("_"," ")}</StatusBadge></div>
        <div className="progress-track" aria-label={`Generation progress ${jobProgress}%`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={jobProgress}><span style={{width:`${jobProgress}%`}}/></div>
        <div className="job-metrics"><div><span>Diffusion step</span><strong>{job.current_step??"—"} / {job.total_steps??"—"}</strong></div><div><span>Model</span><strong>{job.model_id}</strong></div><div><span>Revision</span><strong className="mono breakable">{job.model_revision}</strong></div></div>
        {!isTerminalJobStatus(job.status)&&<div className="job-actions"><LoadingState label="Polling genuine backend state. No completion estimate is fabricated."/><Button type="button" onClick={verifyDuplicateProtection}>Verify duplicate protection</Button>{duplicateCheck&&<p role="status">{duplicateCheck}</p>}</div>}
      </Surface>}

      <section className="result-collection" aria-labelledby="concepts-title">
        <div className="collection-heading"><div><p className="eyebrow">Creative board</p><h2 id="concepts-title">{generated?`${project.results.length} campaign concept${project.results.length===1?"":"s"}`:"No concepts yet"}</h2></div><StatusBadge tone={generated?"good":"wait"}>{generated?"Ready for review":"Awaiting generation"}</StatusBadge></div>
        <div className="results-grid">{project.results.map(result=><CampaignResultCard key={result.result_id} result={result} projectId={id} onChange={update}/>)}</div>
      </section>

      <div className="results-support-grid"><HumanReviewPanel/><SystemStatusPanel remoteInfo={remoteInfo}/></div>
    </div>
  </div>;
}
