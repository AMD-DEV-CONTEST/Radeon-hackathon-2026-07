"use client";

import {type FormEvent,useCallback,useEffect,useRef,useState} from "react";
import {useRouter} from "next/navigation";
import {api} from "@/lib/api";
import {canSubmitExperimental,loadRuntimeConnection,remoteApi} from "@/lib/experimental";
import {clearDraftAsset,DRAFT_ASSET_WORKSPACE,loadDraftAsset,saveDraftAsset} from "@/lib/local-asset-store";
import {clearStudioDraft,createDefaultStudioForm,createStudioDraft,loadStudioDraft,saveStudioDraft,type StudioMode} from "@/lib/studio-draft";
import type {ProjectConfig,SystemInfo} from "@/lib/types";
import {Icon} from "@/components/icons";
import {Button,FormField,FormSection,Surface} from "@/components/primitives";
import {
  BrandColorPicker,
  CreativeStyleSelector,
  ErrorAlert,
  LoadingState,
  OutputFormatSelector,
  RadeonConnectionPanel,
  SectionHeading,
  SegmentedModeControl,
  StatusBadge,
  SystemStatusPanel,
  UploadDropzone,
  WorkflowProgress,
} from "@/components/ui";

const obsoleteCampaignSummaryPositionKey="brandpilotCampaignSummaryPosition";

export default function Studio(){
  const router=useRouter();
  const [form,setForm]=useState<ProjectConfig>(createDefaultStudioForm);
  const [file,setFile]=useState<File|null>(null);
  const [mode,setMode]=useState<StudioMode>("mock");
  const [currentProjectId,setCurrentProjectId]=useState<string|null>(null);
  const [currentProjectMode,setCurrentProjectMode]=useState<StudioMode|null>(null);
  const [draftHydrated,setDraftHydrated]=useState(false);
  const skipNextDraftSave=useRef(false);
  const [remoteInfo,setRemoteInfo]=useState<SystemInfo|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [assetRestoreState,setAssetRestoreState]=useState<"loading"|"empty"|"ready"|"reselect">("loading");
  const [assetNotice,setAssetNotice]=useState("");
  useEffect(()=>{
    sessionStorage.removeItem(obsoleteCampaignSummaryPositionKey);
    let active=true;
    Promise.resolve().then(async()=>{
      const restoredDraft=loadStudioDraft();
      let restoredAsset:File|null=null;
      let assetFailed=false;
      try{restoredAsset=await loadDraftAsset()}catch{assetFailed=true}
      if(!active)return;
      if(restoredDraft){
        setForm(restoredDraft.form);
        setMode(restoredDraft.mode);
        setCurrentProjectId(restoredDraft.currentProjectId);
        setCurrentProjectMode(restoredDraft.currentProjectMode);
      }
      setFile(restoredAsset);
      setAssetRestoreState(assetFailed?"reselect":restoredAsset?"ready":"empty");
      if(assetFailed)setAssetNotice("Image must be selected again.");
      setDraftHydrated(true);
    });
    return()=>{active=false};
  },[]);
  useEffect(()=>{
    if(!draftHydrated)return;
    if(skipNextDraftSave.current){skipNextDraftSave.current=false;return}
    const timer=setTimeout(()=>saveStudioDraft(createStudioDraft({form,mode,currentProjectId,currentProjectMode,assetWorkspaceId:file?DRAFT_ASSET_WORKSPACE:null})),150);
    return()=>clearTimeout(timer);
  },[currentProjectId,currentProjectMode,draftHydrated,file,form,mode]);
  const set=(key:keyof ProjectConfig,value:string|string[])=>setForm(current=>({...current,[key]:value}));
  const handleRemoteStatus=useCallback((status:SystemInfo|null)=>setRemoteInfo(status),[]);
  const handleFile=useCallback((next:File|null)=>{
    setFile(next);setError("");setAssetNotice("");
    if(!next){setAssetRestoreState("empty");void clearDraftAsset().catch(()=>{});return}
    setAssetRestoreState("ready");
    void saveDraftAsset(next).catch(()=>setAssetNotice("The image is ready now but must be selected again after refresh."));
  },[]);
  const selectMode=(next:StudioMode)=>{
    setMode(next);
    setError("");
    if(next==="rocm")setForm(current=>({...current,output_formats:[current.output_formats[0]||"Instagram Square"]}));
  };
  const reset=()=>{
    skipNextDraftSave.current=true;
    clearStudioDraft();
    sessionStorage.removeItem("brandpilotProject");
    sessionStorage.removeItem("brandpilotProjectMode");
    sessionStorage.removeItem("brandpilotRocmJob");
    setCurrentProjectId(null);setCurrentProjectMode(null);
    setForm(createDefaultStudioForm());handleFile(null);setError("");setMode("mock");
  };
  const persistProjectReference=(projectId:string,projectMode:StudioMode)=>{
    setCurrentProjectId(projectId);setCurrentProjectMode(projectMode);
    saveStudioDraft(createStudioDraft({form,mode:projectMode,currentProjectId:projectId,currentProjectMode:projectMode,assetWorkspaceId:file?DRAFT_ASSET_WORKSPACE:null}));
  };
  const submit=async(event:FormEvent)=>{
    event.preventDefault();
    if(busy)return;
    if(!file){setError("Add a product image before generating.");return}
    if(!form.creative_styles.length||!form.output_formats.length){setError("Select a creative style and at least one output format.");return}
    if(mode==="rocm"&&(!remoteInfo||!loadRuntimeConnection())){setError("Verify the experimental Radeon backend connection first.");return}
    if(mode==="rocm"&&(form.creative_styles.length!==1||form.output_formats.length!==1)){setError("Experimental Radeon mode accepts one style and one output format.");return}
    try{
      setBusy(true);setError("");
      if(mode==="mock"){
        const project=await api.create(form);
        await api.upload(project.project_id,file);
        await api.generate(project.project_id);
        persistProjectReference(project.project_id,"mock");
        sessionStorage.setItem("brandpilotProject",project.project_id);
        sessionStorage.setItem("brandpilotProjectMode","mock");
        sessionStorage.removeItem("brandpilotRocmJob");
        router.push(`/results/${project.project_id}`);
        return;
      }
      if(!canSubmitExperimental(!!remoteInfo,false))throw new Error("Experimental Radeon backend is not connected.");
      const project=await remoteApi.create(form);
      await remoteApi.upload(project.project_id,file);
      const job=await remoteApi.generate(project.project_id,form.creative_styles[0],form.output_formats[0]);
      persistProjectReference(project.project_id,"rocm");
      sessionStorage.setItem("brandpilotProject",project.project_id);
      sessionStorage.setItem("brandpilotProjectMode","rocm");
      sessionStorage.setItem("brandpilotRocmJob",job.job_id);
      router.push(`/results/${project.project_id}`);
    }catch(next){
      setError(next instanceof Error?next.message:"Generation request failed.");
    }finally{setBusy(false)}
  };
  const modeCopy=mode==="mock"
    ?"Shape a complete brief and generate four clearly labeled mock campaign directions."
    :"Submit one style and one format to a temporary authenticated Radeon worker. Only measured states are displayed.";

  return <>
    <header className="container pagehead studio-pagehead">
      <div><SectionHeading eyebrow="Creative Studio" title="Build the campaign. Keep control." copy={modeCopy}/><div className="page-status-row"><StatusBadge tone={mode==="mock"?"good":"wait"}>{mode==="mock"?"Mock workspace available":"Experimental opt-in"}</StatusBadge><span>Six focused steps · review required</span></div></div>
      <div className="pagehead-orbit" aria-hidden="true"><span/><span/><Icon name="sparkles"/></div>
    </header>
    <div className="container studio-layout">
      <form className="studio-canvas" onSubmit={submit} aria-busy={!draftHydrated}>
        <Surface className="mode-surface"><div className="mode-surface-copy"><p className="eyebrow">Choose the engine</p><h2>Start with an honest mode.</h2><p>Mock is always available. Radeon appears only through a temporary authenticated connection.</p></div><SegmentedModeControl mode={mode} onChange={selectMode}/>{mode==="rocm"&&<p className="disclosure disclosure-warning"><Icon name="shield"/><span>Experimental only: one GPU job, no CPU fallback, no mock fallback, and no product-preservation guarantee.</span></p>}</Surface>
        {error&&<ErrorAlert message={error}/>}
        <FormSection number="01" title="Product asset" description="Add the rights-cleared image that anchors the campaign."><UploadDropzone file={file} onFile={handleFile} restoreState={assetRestoreState} notice={assetNotice}/></FormSection>
        <FormSection number="02" title="Product details" description="Give the workspace the minimum context needed to frame each direction."><div className="field-grid"><FormField htmlFor="name" label="Product name" hint="Use the customer-facing name."><input id="name" required autoComplete="off" value={form.product_name} onChange={event=>set("product_name",event.target.value)} placeholder="e.g. Aura Bottle"/></FormField><FormField htmlFor="category" label="Product category" hint="Keep it specific and concise."><input id="category" required autoComplete="off" value={form.product_category} onChange={event=>set("product_category",event.target.value)} placeholder="e.g. Reusable drinkware"/></FormField></div></FormSection>
        <FormSection number="03" title="Campaign direction" description="Describe the outcome, audience, and benefits—not the visual execution yet."><div className="field-grid"><FormField htmlFor="goal" label="Campaign objective" hint="What should this campaign achieve?" className="field-span"><input id="goal" required value={form.campaign_goal} onChange={event=>set("campaign_goal",event.target.value)} placeholder="Launch a refined summer collection"/></FormField><FormField htmlFor="audience" label="Target audience" hint="Who should recognize themselves in the work?"><textarea id="audience" required value={form.target_audience} onChange={event=>set("target_audience",event.target.value)} placeholder="Design-conscious professionals who value durable products"/></FormField><FormField htmlFor="benefits" label="Key product benefits" hint="Use concrete, supportable benefits."><textarea id="benefits" required value={form.key_benefits} onChange={event=>set("key_benefits",event.target.value)} placeholder="Reusable, durable, premium finish"/></FormField></div></FormSection>
        <FormSection number="04" title="Brand identity" description="Set the tone and visual anchors that keep concepts coherent."><div className="field-grid"><FormField htmlFor="tone" label="Brand tone" hint="Choose the voice closest to this campaign."><select id="tone" required value={form.brand_tone} onChange={event=>set("brand_tone",event.target.value)}><option value="">Select a tone</option><option>Confident</option><option>Warm</option><option>Refined</option><option>Playful</option></select></FormField><FormField htmlFor="negative" label="Optional guardrails" hint="Describe unwanted visual elements or claims."><input id="negative" value={form.negative_instructions} onChange={event=>set("negative_instructions",event.target.value)} placeholder="Avoid clutter and unsupported product claims"/></FormField><div className="field field-span"><span className="field-label">Brand colors</span><p className="field-hint">Tune the two anchor colors used by the concept system.</p><BrandColorPicker colors={form.brand_colors} setColors={colors=>set("brand_colors",colors)}/></div></div></FormSection>
        <FormSection number="05" title="Creative direction" description="Choose one visual language for a coherent campaign system."><CreativeStyleSelector value={form.creative_styles} setValue={value=>set("creative_styles",value)}/></FormSection>
        <FormSection number="06" title="Output formats" description="Frame the concept for each channel where it needs to work."><OutputFormatSelector value={form.output_formats} setValue={value=>set("output_formats",value)} single={mode==="rocm"}/></FormSection>
        <Surface className="generation-bar"><div><p className="eyebrow">Ready when you are</p><h2>{mode==="mock"?"Create four mock concepts":"Start one Radeon job"}</h2><p>{mode==="mock"?"No GPU is used. Every result is clearly labeled as a mock concept.":"Requires a verified temporary runtime and may take several minutes."}</p></div><div className="generation-actions"><Button className="button-large" variant="primary" disabled={busy||!file||(mode==="rocm"&&!remoteInfo)} loading={busy}>{busy?"Preparing campaign":mode==="mock"?"Generate mock campaign":"Start Radeon job"}<Icon name="arrow"/></Button><Button type="button" variant="ghost" className="reset-workspace-button" aria-label="Reset campaign workspace" disabled={busy} onClick={reset}>Reset workspace</Button></div>{busy&&<LoadingState label={mode==="rocm"?"Creating project, uploading the asset, and queuing one measured GPU job…":"Creating the project and four mock concepts…"}/>}</Surface>
      </form>
      <aside className="studio-sidebar" aria-label="Workspace status"><div className="studio-sidebar-stack">
        <Surface className="dashboard-card campaign-summary" aria-busy={!draftHydrated}><header className="panel-header"><span className="panel-icon"><Icon name="palette"/></span><div><p className="eyebrow">Live brief</p><h2>Campaign summary</h2></div><StatusBadge tone={mode==="mock"?"good":"wait"}>{draftHydrated?mode:"loading"}</StatusBadge></header><dl className="summary-list"><div><dt>Product</dt><dd>{draftHydrated?form.product_name||"Not named":"Restoring draft…"}</dd></div><div><dt>Style</dt><dd>{draftHydrated?form.creative_styles[0]||"Not selected":"Restoring…"}</dd></div><div><dt>Formats</dt><dd>{draftHydrated?form.output_formats.length:"—"}</dd></div><div><dt>Asset</dt><dd>{file?"Ready":assetRestoreState==="loading"?"Restoring…":assetRestoreState==="reselect"?"Reselect required":"Required"}</dd></div></dl></Surface>
        <RadeonConnectionPanel onStatus={handleRemoteStatus}/>
        <Surface className="dashboard-card"><header className="panel-header"><span className="panel-icon"><Icon name="layers"/></span><div><p className="eyebrow">Workspace</p><h2>Progress</h2></div></header><WorkflowProgress asset={!!file} generated={false}/></Surface>
        <SystemStatusPanel remoteInfo={remoteInfo}/>
        <Surface className="dashboard-card safety-card"><header className="panel-header"><span className="panel-icon"><Icon name="shield"/></span><div><p className="eyebrow">Review boundary</p><h2>Human stays in control</h2></div></header><p className="panel-note">Concepts remain disclosed and cannot be exported from this prototype. Product identity, packaging text, and logo preservation are not claimed.</p></Surface>
      </div></aside>
    </div>
  </>;
}
