"use client";
export default function ProjectBuilding({selected=false,dimmed=false}:{selected?:boolean;dimmed?:boolean}) {
 const o=dimmed?0.25:1;
 return <group>
  <mesh castShadow receiveShadow position={[0,0.9,0]}><boxGeometry args={[3.3,1.8,2.8]}/><meshStandardMaterial color="#332a31" roughness={0.68} metalness={0.16} transparent opacity={o}/></mesh>
  <mesh castShadow position={[-0.7,2.05,-0.25]}><boxGeometry args={[1.35,0.55,1.8]}/><meshStandardMaterial color="#4a3945" roughness={0.55} transparent opacity={o}/></mesh>
  <mesh castShadow position={[0.85,1.95,-0.35]}><cylinderGeometry args={[0.12,0.12,1.6,10]}/><meshStandardMaterial color="#58616b" metalness={0.7} roughness={0.3}/></mesh>
  <mesh position={[0,0.7,1.41]}><planeGeometry args={[0.8,1.2]}/><meshStandardMaterial color="#12161c"/></mesh>
  {[-1.05,1.05].map(x=><mesh key={x} position={[x,1.15,1.415]}><planeGeometry args={[0.58,0.62]}/><meshStandardMaterial color="#d4b5c9" emissive="#8b4b70" emissiveIntensity={selected?0.9:0.35} transparent opacity={dimmed?0.08:0.7}/></mesh>)}
  <mesh position={[0,1.62,1.43]}><boxGeometry args={[1.5,0.13,0.08]}/><meshStandardMaterial color={selected?"#f9a8d4":"#76546c"} emissive="#9d174d" emissiveIntensity={selected?1.2:0.2}/></mesh>
 </group>;
}
