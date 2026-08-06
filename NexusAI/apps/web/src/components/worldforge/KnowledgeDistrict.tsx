"use client";
import ProximityLabel from "./ProximityLabel";
import * as THREE from "three";
import type { DistrictData } from "./types";
export default function KnowledgeDistrict({district}:{district:DistrictData}) {
 const radius=Math.max(6.2,5.4+district.members.length*0.65);
 return <group position={district.position}>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]} position={[0,-0.035,0]}>
   <circleGeometry args={[radius,64]}/>
   <meshStandardMaterial color="#111c19" roughness={0.96} metalness={0.02} transparent opacity={0.82} side={THREE.DoubleSide}/>
  </mesh>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]} position={[0,-0.015,0]}>
   <ringGeometry args={[radius-0.22,radius,64]}/>
   <meshStandardMaterial color="#31483e" roughness={0.9} transparent opacity={0.55}/>
  </mesh>
  <ProximityLabel position={[0,0.22,-radius+0.65]} near={7} far={20} worldFar={30} major>
   <div className="pointer-events-none whitespace-nowrap rounded-md border border-white/10 bg-black/65 px-3 py-1 text-[8px] font-semibold uppercase tracking-[0.22em] text-white/65 backdrop-blur-md">{district.name} <span className="text-white/30">DISTRICT</span></div>
  </ProximityLabel>
 </group>;
}
