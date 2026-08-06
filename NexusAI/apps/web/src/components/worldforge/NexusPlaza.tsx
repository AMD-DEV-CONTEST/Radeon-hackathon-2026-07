"use client";
import { Html } from "@react-three/drei";
export default function NexusPlaza({position=[0,0,0] as [number,number,number]}) {
 return <group position={position}>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]} position={[0,-0.04,0]}><circleGeometry args={[4.4,64]}/><meshStandardMaterial color="#202a2c" roughness={0.9}/></mesh>
  <mesh receiveShadow rotation={[-Math.PI/2,0,0]} position={[0,-0.025,0]}><ringGeometry args={[3.25,3.45,64]}/><meshStandardMaterial color="#44535a" roughness={0.75}/></mesh>
  <mesh castShadow position={[0,0.48,0]}><cylinderGeometry args={[0.8,1.05,0.95,12]}/><meshStandardMaterial color="#27343a" metalness={0.35} roughness={0.45}/></mesh>
  <mesh position={[0,1.42,0]}><octahedronGeometry args={[0.42,0]}/><meshStandardMaterial color="#a5f3fc" emissive="#0891b2" emissiveIntensity={1.15} metalness={0.55} roughness={0.22}/></mesh>
  <Html position={[0,2.2,0]} center distanceFactor={24}><div className="pointer-events-none whitespace-nowrap rounded-md border border-white/10 bg-black/65 px-3 py-1 text-[8px] uppercase tracking-[0.28em] text-cyan-100/70">Nexus Plaza</div></Html>
 </group>;
}
