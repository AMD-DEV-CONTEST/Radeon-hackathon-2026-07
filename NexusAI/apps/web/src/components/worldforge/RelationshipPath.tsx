"use client";
import ProximityLabel from "./ProximityLabel";
import * as THREE from "three";
import type { WorldForgeRelationship } from "@/lib/api";
import type { Vec3 } from "./types";
import { RELATIONSHIP_COLORS } from "./colors";
export default function RelationshipPath({relationship,source,target,highlighted,dimmed}:{relationship:WorldForgeRelationship;source:Vec3;target:Vec3;highlighted:boolean;dimmed:boolean}) {
 const start=new THREE.Vector3(source[0],0.08,source[2]), end=new THREE.Vector3(target[0],0.08,target[2]), midpoint=start.clone().add(end).multiplyScalar(0.5), length=start.distanceTo(end), direction=end.clone().sub(start).normalize();
 const quaternion=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),direction);
 const color=RELATIONSHIP_COLORS[relationship.relationship_type.toUpperCase()]??"#64748b";
 return <group>
  <mesh position={midpoint} quaternion={quaternion}><cylinderGeometry args={[highlighted?0.16:0.11,highlighted?0.16:0.11,length,10]}/><meshStandardMaterial color="#18232c" roughness={0.85} transparent opacity={dimmed?0.08:0.62}/></mesh>
  <mesh position={[midpoint.x,midpoint.y+0.035,midpoint.z]} quaternion={quaternion}><cylinderGeometry args={[0.025,0.025,length,8]}/><meshBasicMaterial color={color} transparent opacity={dimmed?0.05:highlighted?0.95:0.4}/></mesh>
  {highlighted&&<ProximityLabel position={[midpoint.x,0.55,midpoint.z]} near={4} far={11}><div className="pointer-events-none whitespace-nowrap rounded-full border border-white/10 bg-black/80 px-2 py-0.5 text-[7px] font-semibold uppercase tracking-[0.18em] text-white/75 backdrop-blur-md">{relationship.relationship_type.replaceAll("_"," ")}</div></ProximityLabel>}
 </group>;
}