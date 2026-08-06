"use client";
export default function ContextBuilding({position,rotation=0,scale=1}:{position:[number,number,number];rotation?:number;scale?:number}) {
 return <group position={position} rotation={[0,rotation,0]} scale={scale}>
  <mesh castShadow receiveShadow position={[0,0.78,0]}><boxGeometry args={[1.8,1.56,1.5]}/><meshStandardMaterial color="#20272d" roughness={0.78} metalness={0.08}/></mesh>
  <mesh castShadow position={[-0.28,1.72,-0.05]}><boxGeometry args={[1.15,0.34,1.18]}/><meshStandardMaterial color="#313b42" roughness={0.66}/></mesh>
  <mesh castShadow position={[0.58,1.55,-0.22]}><boxGeometry args={[0.48,0.62,0.72]}/><meshStandardMaterial color="#29343b" roughness={0.7}/></mesh>
  {[-0.5,0,0.5].map(x=><mesh key={x} position={[x,1.02,0.756]}><planeGeometry args={[0.27,0.42]}/><meshStandardMaterial color="#8bb7c1" emissive="#315b65" emissiveIntensity={0.2}/></mesh>)}
  <mesh position={[0,0.48,0.76]}><planeGeometry args={[0.38,0.76]}/><meshStandardMaterial color="#10161a"/></mesh>
 </group>;
}
