"use client";
import * as THREE from "three";
import type { LayoutData } from "./types";
import { getLayoutBounds } from "./layout";

export default function WorldTerrain({layout}:{layout:LayoutData}) {
 const {center,radius}=getLayoutBounds(layout);
 const r=Math.max(18,Math.min(38,radius+5));
 return <group position={[center[0],0,center[2]]}>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]} position={[0,-0.18,0]}>
   <circleGeometry args={[r,96]}/><meshStandardMaterial color="#09120f" roughness={0.98} metalness={0.02}/>
  </mesh>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]} position={[0,-0.16,0]}>
   <ringGeometry args={[r-2.5,r,96]}/><meshStandardMaterial color="#05090b" roughness={1}/>
  </mesh>
  <gridHelper args={[r*1.65,Math.max(16,Math.round(r/1.7)),"#173039","#0d171b"]} position={[0,-0.13,0]}/>
 </group>;
}
