import type { EntityKind } from "./types";

export type WorldAssetDefinition={
 id:string;
 kind:EntityKind;
 url:string;
 scale:number;
 yOffset:number;
 rotationY?:number;
};

const ASSETS:Partial<Record<EntityKind,WorldAssetDefinition[]>>={
 PERSON:[],
 PLACE:[],
 PROJECT:[],
 ORGANIZATION:[],
 SYSTEM:[],
 UNKNOWN:[],
};

export function registerWorldAsset(asset:WorldAssetDefinition){(ASSETS[asset.kind]??=[]).push(asset)}
export function getWorldAsset(kind:EntityKind){return ASSETS[kind]?.[0]??null}

/*
Add production GLB files under public/worldforge/assets/ and register them here:
registerWorldAsset({id:"person-default",kind:"PERSON",url:"/worldforge/assets/characters/person.glb",scale:1,yOffset:0});
The renderer deliberately keeps primitive fallbacks until a registered asset exists.
*/
