"use client";
import * as THREE from "three";
import type { DistrictData,Vec3 } from "./types";
function Road({a,b,width=1.65}:{a:Vec3;b:Vec3;width?:number}) {
 const s=new THREE.Vector3(a[0],0.015,a[2]),e=new THREE.Vector3(b[0],0.015,b[2]),m=s.clone().add(e).multiplyScalar(.5),len=s.distanceTo(e),ang=Math.atan2(e.x-s.x,e.z-s.z);
 return <group position={[m.x,0.015,m.z]} rotation={[0,ang,0]}>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]}><planeGeometry args={[width,len]}/><meshStandardMaterial color="#171e22" roughness={0.96}/></mesh>
  <mesh rotation={[-Math.PI/2,0,0]} position={[0,0.008,0]}><planeGeometry args={[0.035,len*.9]}/><meshBasicMaterial color="#64747a" transparent opacity={0.35}/></mesh>
 </group>
}
export default function DistrictRoadNetwork({districts,center=[0,0,0]}:{districts:DistrictData[];center?:Vec3}) {
 return <>{districts.map(d=><Road key={d.id} a={center} b={d.position}/>)}</>;
}
