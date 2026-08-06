"use client";
export default function OrganizationBuilding({selected=false,dimmed=false}:{selected?:boolean;dimmed?:boolean}) {
 const o=dimmed?0.25:1;
 const windows=[-0.82,-0.28,0.28,0.82];
 return <group>
  <mesh castShadow receiveShadow position={[0,1.35,0]}><boxGeometry args={[3.6,2.7,2.7]}/><meshStandardMaterial color="#252c36" roughness={0.58} metalness={0.22} transparent opacity={o}/></mesh>
  <mesh castShadow position={[0,2.95,-0.15]}><boxGeometry args={[3.0,0.5,2.2]}/><meshStandardMaterial color="#333e4b" roughness={0.48} transparent opacity={o}/></mesh>
  {windows.map(x=>[1.15,2.0].map(y=><mesh key={`${x}-${y}`} position={[x,y,1.356]}><planeGeometry args={[0.38,0.5]}/><meshStandardMaterial color="#a9d8e8" emissive="#39758b" emissiveIntensity={0.55} transparent opacity={dimmed?0.08:0.75}/></mesh>))}
  <mesh position={[0,0.65,1.37]}><planeGeometry args={[0.72,1.18]}/><meshStandardMaterial color="#0b1117" metalness={0.5} roughness={0.3} transparent opacity={o}/></mesh>
  <mesh position={[0,1.52,1.39]}><boxGeometry args={[1.25,0.12,0.08]}/><meshStandardMaterial color={selected?"#c4b5fd":"#607080"} emissive={selected?"#7c3aed":"#111827"} emissiveIntensity={selected?1.2:0.2}/></mesh>
 </group>;
}
