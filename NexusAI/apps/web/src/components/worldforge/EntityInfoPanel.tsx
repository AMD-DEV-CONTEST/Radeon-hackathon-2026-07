"use client";
import type { WorldForgeEntity, WorldForgeRelationship } from "@/lib/api";
export default function EntityInfoPanel({entity,entities,relationships,onClose,onSelectEntity}:{entity:WorldForgeEntity;entities:WorldForgeEntity[];relationships:WorldForgeRelationship[];onClose:()=>void;onSelectEntity:(e:WorldForgeEntity)=>void}) {
 const byId=new Map(entities.map(e=>[e.id,e]));
 const connections=relationships.filter(r=>r.source_entity_id===entity.id||r.target_entity_id===entity.id).map(r=>({relationship:r,other:byId.get(r.source_entity_id===entity.id?r.target_entity_id:r.source_entity_id)})).filter(x=>x.other);
 return <div className="pointer-events-auto absolute right-6 top-24 z-30 w-[320px] overflow-hidden rounded-2xl border border-white/10 bg-[#05080d]/90 shadow-2xl backdrop-blur-xl">
  <div className="border-b border-white/10 px-5 py-4"><div className="flex items-start justify-between gap-4"><div><div className="text-[9px] uppercase tracking-[0.3em] text-cyan-200/60">{entity.entity_type}</div><h2 className="mt-1 text-lg font-semibold text-white">{entity.name}</h2></div><button type="button" onClick={onClose} className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-white/50 hover:bg-white/10 hover:text-white">ESC</button></div>{entity.description&&<p className="mt-3 text-xs leading-5 text-white/55">{entity.description}</p>}</div>
  <div className="px-5 py-4"><div className="text-[9px] font-semibold uppercase tracking-[0.28em] text-white/35">Connections · {connections.length}</div><div className="mt-3 space-y-2">
   {connections.length===0&&<div className="rounded-lg border border-white/5 bg-white/[0.025] px-3 py-3 text-xs text-white/35">No direct relationships.</div>}
   {connections.map(({relationship,other})=><button type="button" key={relationship.id} onClick={()=>other&&onSelectEntity(other)} className="flex w-full items-center justify-between gap-4 rounded-lg border border-white/5 bg-white/[0.025] px-3 py-2.5 text-left hover:border-cyan-300/20 hover:bg-cyan-300/[0.04]"><div><div className="text-xs font-medium text-white/80">{other?.name}</div><div className="mt-0.5 text-[8px] uppercase tracking-[0.18em] text-cyan-200/45">{relationship.relationship_type.replaceAll("_"," ")}</div></div><span className="text-white/25">›</span></button>)}
  </div></div>
 </div>;
}