import type { WorldForgeData } from "@/lib/api";
import type { LayoutData } from "./types";
import { entityKind } from "./utils";

export type SemanticCollider={x:number;z:number;halfW:number;halfD:number};

export function buildSemanticColliders(data:WorldForgeData|null,layout:LayoutData,playerRadius=0.38):SemanticCollider[]{
 if(!data)return[];
 return data.entities.flatMap(entity=>{
  const p=layout.positions.get(entity.id); if(!p)return[];
  const kind=entityKind(entity.entity_type);
  if(kind==="PERSON"||kind==="PLACE")return[];
  const size=kind==="ORGANIZATION"?[1.8,1.35]:kind==="PROJECT"?[1.65,1.4]:kind==="SYSTEM"?[1.55,1.3]:[1.2,1.1];
  return [{x:p[0],z:p[2],halfW:size[0]+playerRadius,halfD:size[1]+playerRadius}];
 });
}
