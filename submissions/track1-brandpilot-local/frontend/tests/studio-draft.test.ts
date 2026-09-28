import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {DRAFT_ASSET_WORKSPACE} from "../lib/local-asset-store.ts";
import {clearStudioDraft,createDefaultStudioForm,createStudioDraft,loadStudioDraft,saveStudioDraft,STUDIO_DRAFT_KEY,STUDIO_DRAFT_VERSION,validateStudioForm} from "../lib/studio-draft.ts";
import type {ProjectConfig} from "../lib/types.ts";

class MemoryStorage{
  values=new Map<string,string>();
  getItem(key:string){return this.values.get(key)??null}
  setItem(key:string,value:string){this.values.set(key,value)}
  removeItem(key:string){this.values.delete(key)}
}

const read=(path:string)=>readFileSync(new URL(path,import.meta.url),"utf8");
const exactForm:ProjectConfig={
  product_name:"Astra Travel Bottle",
  product_category:"Reusable drinkware",
  campaign_goal:"Launch a premium reusable bottle for everyday work, travel, and fitness.",
  target_audience:"Young professionals, students, commuters, and fitness-focused customers aged 18 to 35.",
  key_benefits:"Keeps drinks cold, reusable, leak-resistant, durable, lightweight, and easy to carry.",
  brand_tone:"Confident",
  brand_colors:["#E52F3C","#111318"],
  negative_instructions:"Keep the product realistic. Avoid unsupported claims.",
  creative_styles:["Luxury"],
  output_formats:["Instagram Square","Instagram Portrait"],
};

function roundTrip(){
  const storage=new MemoryStorage();
  const draft=createStudioDraft({form:exactForm,mode:"mock",currentProjectId:"6c239e13-5d82-4b0f-9317-65b5c21c6aa2",currentProjectMode:"mock",assetWorkspaceId:DRAFT_ASSET_WORKSPACE});
  assert.equal(saveStudioDraft(draft,storage),true);
  return loadStudioDraft(storage);
}

for(const [label,key] of [
  ["product name","product_name"],
  ["product category","product_category"],
  ["campaign objective","campaign_goal"],
  ["target audience","target_audience"],
  ["key benefits","key_benefits"],
  ["brand tone","brand_tone"],
  ["guardrails","negative_instructions"],
] as const){
  test(`Studio draft restores ${label}`,()=>assert.equal(roundTrip()?.form[key],validateStudioForm(exactForm)[key]));
}

test("Studio draft restores brand colors",()=>assert.deepEqual(roundTrip()?.form.brand_colors,["#e52f3c","#111318"]));
test("Studio draft restores one creative style",()=>assert.deepEqual(roundTrip()?.form.creative_styles,["Luxury"]));
test("Studio draft restores multiple output formats",()=>assert.deepEqual(roundTrip()?.form.output_formats,["Instagram Square","Instagram Portrait"]));

test("draft schema restores mode, project reference, and safe asset reference",()=>{
  const restored=roundTrip();
  assert.equal(restored?.version,STUDIO_DRAFT_VERSION);
  assert.equal(restored?.mode,"mock");
  assert.equal(restored?.currentProjectId,"6c239e13-5d82-4b0f-9317-65b5c21c6aa2");
  assert.equal(restored?.currentProjectMode,"mock");
  assert.equal(restored?.assetWorkspaceId,DRAFT_ASSET_WORKSPACE);
});

test("restored values are not overwritten by defaults",()=>{
  const restored=roundTrip();
  assert.notDeepEqual(restored?.form,createDefaultStudioForm());
  assert.equal(restored?.form.product_name,"Astra Travel Bottle");
});

test("malformed and old drafts fall back safely",()=>{
  const storage=new MemoryStorage();
  storage.setItem(STUDIO_DRAFT_KEY,"not-json");
  assert.equal(loadStudioDraft(storage),null);
  storage.setItem(STUDIO_DRAFT_KEY,JSON.stringify({version:99,form:exactForm}));
  assert.equal(loadStudioDraft(storage),null);
  storage.setItem(STUDIO_DRAFT_KEY,JSON.stringify({version:1,mode:"unsafe",form:{product_name:"Safe name",brand_tone:"Invalid",brand_colors:["javascript:bad"],creative_styles:["Unknown"],output_formats:[]}}));
  const restored=loadStudioDraft(storage);
  assert.equal(restored?.form.product_name,"Safe name");
  assert.equal(restored?.form.brand_tone,"");
  assert.deepEqual(restored?.form.brand_colors,["#e52f3c","#111318"]);
  assert.deepEqual(restored?.form.creative_styles,["Luxury"]);
  assert.deepEqual(restored?.form.output_formats,["Instagram Square"]);
});

test("Reset clears only the Studio draft key",()=>{
  const storage=new MemoryStorage();
  storage.setItem(STUDIO_DRAFT_KEY,"draft");
  storage.setItem("unrelated","keep");
  clearStudioDraft(storage);
  assert.equal(storage.getItem(STUDIO_DRAFT_KEY),null);
  assert.equal(storage.getItem("unrelated"),"keep");
});

test("Studio draft never contains Radeon connection credentials or image bytes",()=>{
  const serialized=JSON.stringify(createStudioDraft({form:exactForm,mode:"rocm",assetWorkspaceId:DRAFT_ASSET_WORKSPACE}));
  assert.doesNotMatch(serialized,/endpoint|access.?code|auth|token|tunnel|blob:|base64|data:image/i);
  assert.match(serialized,/studio-draft/);
});

test("Studio integration hydrates before saving and clears related draft state on reset",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.match(studio,/const restoredDraft=loadStudioDraft\(\)/);
  assert.match(studio,/if\(!draftHydrated\)return/);
  assert.match(studio,/setTimeout\(\(\)=>saveStudioDraft[\s\S]*,150\)/);
  assert.match(studio,/clearStudioDraft\(\)/);
  assert.match(studio,/clearDraftAsset\(\)/);
  assert.match(studio,/sessionStorage\.removeItem\("brandpilotProject"\)/);
  assert.match(studio,/draftHydrated\?form\.product_name\|\|"Not named":"Restoring draft…"/);
});

test("successful generation saves the project reference before navigation without creating on mount",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.match(studio,/persistProjectReference\(project\.project_id,"mock"\);[\s\S]*router\.push/);
  assert.match(studio,/persistProjectReference\(project\.project_id,"rocm"\);[\s\S]*router\.push/);
  const mountEffect=studio.slice(studio.indexOf("useEffect(()=>{"),studio.indexOf("const set="));
  assert.doesNotMatch(mountEffect,/api\.create|remoteApi\.create/);
});
