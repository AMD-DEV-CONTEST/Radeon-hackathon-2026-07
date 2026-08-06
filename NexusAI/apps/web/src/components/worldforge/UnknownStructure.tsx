"use client";
export default function UnknownStructure({selected=false,dimmed=false}:{selected?:boolean;dimmed?:boolean}) {
 const o=dimmed?0.25:1;
 return <group>
  <mesh castShadow receiveShadow position={[0,0.8,0]}><boxGeometry args={[2.4,1.6,2.2]}/><meshStandardMaterial color="#2b3440" roughness={0.7} transparent opacity={o}/></mesh>
  <mesh castShadow position={[0,1.85,0]}><coneGeometry args={[1.55,0.75,4]}/><meshStandardMaterial color="#3c4858" roughness={0.75} transparent opacity={o}/></mesh>
  <mesh position={[0,0.7,1.11]}><planeGeometry args={[0.62,0.9]}/><meshStandardMaterial color="#111827"/></mesh>
  {selected&&<pointLight position={[0,1.8,0]} intensity={2} distance={4} color="#93c5fd"/>}
 </group>;
}
