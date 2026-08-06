"use client";
import type { DistrictData } from "./types";
import StreetFurniture from "./StreetFurniture";
import ContextBuilding from "./ContextBuilding";
import DistrictTree from "./DistrictTree";

function hash(s:string){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return h>>>0}
function rand(seed:number){const x=Math.sin(seed*12.9898)*43758.5453;return x-Math.floor(x)}

export default function DistrictEnvironment({district}:{district:DistrictData}) {
 const radius=Math.max(6.2,5.4+district.members.length*0.65);
 const seed=hash(district.id);
 const ring=(count:number,r:number,offset=0)=>Array.from({length:count},(_,i)=>{
   const a=(i/count)*Math.PI*2+offset;
   return [district.position[0]+Math.cos(a)*r,0,district.position[2]+Math.sin(a)*r] as [number,number,number];
 });
 const lamps=ring(6,radius-1,0.2);
 const trees=ring(8,radius+1.25,0.45);
 const buildings=ring(Math.min(5,Math.max(3,3+district.members.length)),radius+2.6,0.8);
 return <>
  {lamps.map((p,i)=><StreetFurniture key={`lamp-${district.id}-${i}`} position={p}/>)}
  {trees.map((p,i)=><DistrictTree key={`tree-${district.id}-${i}`} position={p} scale={0.62+rand(seed+i)*0.28}/>)}
  {buildings.map((p,i)=><ContextBuilding key={`ctx-${district.id}-${i}`} position={p} rotation={(i/buildings.length)*Math.PI*2+Math.PI/2} scale={0.82+rand(seed+50+i)*0.28}/>)}
 </>;
}
