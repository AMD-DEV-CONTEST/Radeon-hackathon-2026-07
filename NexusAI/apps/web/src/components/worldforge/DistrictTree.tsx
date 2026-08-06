"use client";
export default function DistrictTree({position,scale=1}:{position:[number,number,number];scale?:number}) {
 return <group position={position} scale={scale}>
  <mesh castShadow position={[0,0.72,0]}><cylinderGeometry args={[0.08,0.11,1.44,8]}/><meshStandardMaterial color="#46382c" roughness={0.95}/></mesh>
  <mesh castShadow position={[0,1.65,0]}><icosahedronGeometry args={[0.72,1]}/><meshStandardMaterial color="#214b37" roughness={0.92}/></mesh>
 </group>;
}
