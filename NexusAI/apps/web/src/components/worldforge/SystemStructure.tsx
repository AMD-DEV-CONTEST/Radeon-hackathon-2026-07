"use client";
export default function SystemStructure({selected=false,dimmed=false}:{selected?:boolean;dimmed?:boolean}) {
 const o=dimmed?0.24:1;
 return <group>
  <mesh castShadow receiveShadow position={[0,1.15,0]}><boxGeometry args={[3.1,2.3,2.6]}/><meshStandardMaterial color="#15262d" roughness={0.42} metalness={0.5} transparent opacity={o}/></mesh>
  <mesh castShadow position={[0,2.55,0]}><boxGeometry args={[2.45,0.5,2.0]}/><meshStandardMaterial color="#203b44" roughness={0.38} metalness={0.58} transparent opacity={o}/></mesh>
  {[-0.9,-0.3,0.3,0.9].map(x=><mesh key={x} position={[x,1.35,1.306]}><planeGeometry args={[0.28,0.75]}/><meshStandardMaterial color="#7dd3df" emissive="#0e7490" emissiveIntensity={selected?1.4:0.55} transparent opacity={dimmed?0.08:0.75}/></mesh>)}
  <mesh position={[0,0.62,1.32]}><planeGeometry args={[0.68,1.05]}/><meshStandardMaterial color="#071318" metalness={0.65}/></mesh>
  <mesh position={[0,3.05,0]}><cylinderGeometry args={[0.08,0.08,0.8,8]}/><meshStandardMaterial color="#536b73" metalness={0.8}/></mesh>
  <mesh position={[0,3.48,0]}><sphereGeometry args={[0.13,12,12]}/><meshStandardMaterial color="#cffafe" emissive="#22d3ee" emissiveIntensity={selected?3:1.2}/></mesh>
 </group>;
}
