"use client";
import type { WorldForgeEntity } from "@/lib/api";

export default function PersonEntity({ selected=false, dimmed=false }: { entity: WorldForgeEntity; selected?: boolean; dimmed?: boolean }) {
  const opacity=dimmed?0.28:1;
  return <group>
    <mesh castShadow position={[0,1.72,0]}><sphereGeometry args={[0.22,20,20]}/><meshStandardMaterial color="#cda582" roughness={0.9} transparent opacity={opacity}/></mesh>
    <mesh castShadow position={[0,1.08,0]}><capsuleGeometry args={[0.25,0.72,6,14]}/><meshStandardMaterial color={selected?"#d6a94b":"#27384b"} roughness={0.72} transparent opacity={opacity}/></mesh>
    {[-0.14,0.14].map(x=><mesh key={x} castShadow position={[x,0.38,0]}><capsuleGeometry args={[0.075,0.56,5,10]}/><meshStandardMaterial color="#18202c" roughness={0.85} transparent opacity={opacity}/></mesh>)}
    {selected&&<pointLight position={[0,1.4,0]} intensity={2.5} distance={4} color="#fde68a"/>}
  </group>;
}
