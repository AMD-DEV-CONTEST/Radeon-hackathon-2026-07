import {DRAFT_ASSET_WORKSPACE} from "./local-asset-store.ts";
import type {ProjectConfig} from "./types";

export const STUDIO_DRAFT_KEY="brandpilotStudioDraftV1";
export const STUDIO_DRAFT_VERSION=1;

export type StudioMode="mock"|"rocm";

export type StudioDraft={
  version:typeof STUDIO_DRAFT_VERSION;
  mode:StudioMode;
  form:ProjectConfig;
  currentProjectId:string|null;
  currentProjectMode:StudioMode|null;
  assetWorkspaceId:typeof DRAFT_ASSET_WORKSPACE|null;
  updatedAt:number;
};

type StorageLike=Pick<Storage,"getItem"|"setItem"|"removeItem">;

const tones=new Set(["","Confident","Warm","Refined","Playful"]);
const styles=new Set(["Luxury","Minimal Studio","Lifestyle","Promotional Sale"]);
const formats=new Set(["Instagram Square","Instagram Portrait","Story / Reel Cover","Landscape Advertisement"]);
const projectIdPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const colorPattern=/^#[0-9a-f]{6}$/i;

export function createDefaultStudioForm():ProjectConfig{
  return {
    product_name:"",
    product_category:"",
    campaign_goal:"",
    target_audience:"",
    key_benefits:"",
    brand_tone:"",
    brand_colors:["#e52f3c","#111318"],
    negative_instructions:"",
    creative_styles:["Luxury"],
    output_formats:["Instagram Square"],
  };
}

function safeString(value:unknown,fallback:string,maxLength=4000):string{
  return typeof value==="string"&&value.length<=maxLength?value:fallback;
}

function safeColor(value:unknown,fallback:string):string{
  return typeof value==="string"&&colorPattern.test(value)?value.toLowerCase():fallback;
}

function safeSingleChoice(value:unknown,allowed:Set<string>,fallback:string[]):string[]{
  if(!Array.isArray(value))return [...fallback];
  const choice=value.find(item=>typeof item==="string"&&allowed.has(item));
  return choice?[choice]:[...fallback];
}

function safeMultipleChoices(value:unknown,allowed:Set<string>,fallback:string[]):string[]{
  if(!Array.isArray(value))return [...fallback];
  const choices=[...new Set(value.filter((item):item is string=>typeof item==="string"&&allowed.has(item)))];
  return choices.length?choices:[...fallback];
}

export function validateStudioForm(value:unknown):ProjectConfig{
  const fallback=createDefaultStudioForm();
  const candidate=value&&typeof value==="object"?value as Partial<Record<keyof ProjectConfig,unknown>>:{};
  const candidateColors=Array.isArray(candidate.brand_colors)?candidate.brand_colors:[];
  return {
    product_name:safeString(candidate.product_name,fallback.product_name,200),
    product_category:safeString(candidate.product_category,fallback.product_category,200),
    campaign_goal:safeString(candidate.campaign_goal,fallback.campaign_goal),
    target_audience:safeString(candidate.target_audience,fallback.target_audience),
    key_benefits:safeString(candidate.key_benefits,fallback.key_benefits),
    brand_tone:typeof candidate.brand_tone==="string"&&tones.has(candidate.brand_tone)?candidate.brand_tone:fallback.brand_tone,
    brand_colors:[safeColor(candidateColors[0],fallback.brand_colors[0]),safeColor(candidateColors[1],fallback.brand_colors[1])],
    negative_instructions:safeString(candidate.negative_instructions,fallback.negative_instructions),
    creative_styles:safeSingleChoice(candidate.creative_styles,styles,fallback.creative_styles),
    output_formats:safeMultipleChoices(candidate.output_formats,formats,fallback.output_formats),
  };
}

export function createStudioDraft({form,mode,currentProjectId=null,currentProjectMode=null,assetWorkspaceId=null}:{form:ProjectConfig;mode:StudioMode;currentProjectId?:string|null;currentProjectMode?:StudioMode|null;assetWorkspaceId?:string|null}):StudioDraft{
  const safeMode:StudioMode=mode==="rocm"?"rocm":"mock";
  const validatedForm=validateStudioForm(form);
  const safeProjectId=typeof currentProjectId==="string"&&projectIdPattern.test(currentProjectId)?currentProjectId:null;
  if(safeMode==="rocm")validatedForm.output_formats=[validatedForm.output_formats[0]];
  return {
    version:STUDIO_DRAFT_VERSION,
    mode:safeMode,
    form:validatedForm,
    currentProjectId:safeProjectId,
    currentProjectMode:safeProjectId&&(currentProjectMode==="mock"||currentProjectMode==="rocm")?currentProjectMode:null,
    assetWorkspaceId:assetWorkspaceId===DRAFT_ASSET_WORKSPACE?DRAFT_ASSET_WORKSPACE:null,
    updatedAt:Date.now(),
  };
}

export function loadStudioDraft(storage:StorageLike=window.localStorage):StudioDraft|null{
  try{
    const raw=storage.getItem(STUDIO_DRAFT_KEY);
    if(!raw)return null;
    const parsed:unknown=JSON.parse(raw);
    if(!parsed||typeof parsed!=="object"||(parsed as {version?:unknown}).version!==STUDIO_DRAFT_VERSION)return null;
    const candidate=parsed as Partial<StudioDraft>;
    return createStudioDraft({
      form:validateStudioForm(candidate.form),
      mode:candidate.mode==="rocm"?"rocm":"mock",
      currentProjectId:candidate.currentProjectId,
      currentProjectMode:candidate.currentProjectMode,
      assetWorkspaceId:candidate.assetWorkspaceId,
    });
  }catch{return null}
}

export function saveStudioDraft(draft:StudioDraft,storage:StorageLike=window.localStorage):boolean{
  try{storage.setItem(STUDIO_DRAFT_KEY,JSON.stringify(draft));return true}catch{return false}
}

export function clearStudioDraft(storage:StorageLike=window.localStorage):void{
  try{storage.removeItem(STUDIO_DRAFT_KEY)}catch{}
}
