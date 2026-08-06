"use client";
export default function PlaceLandmark({selected=false,dimmed=false}:{selected?:boolean;dimmed?:boolean}) {
 const o=dimmed?0.22:1;
 return <group>
  <mesh receiveShadow position={[0,0.08,0]}><cylinderGeometry args={[2.2,2.2,0.16,40]}/><meshStandardMaterial color="#20362e" roughness={0.9} transparent opacity={o}/></mesh>
  <mesh castShadow position={[0,0.75,0]}><cylinderGeometry args={[0.48,0.62,1.5,10]}/><meshStandardMaterial color="#4d5d55" roughness={0.75} transparent opacity={o}/></mesh>
  <mesh castShadow position={[0,1.75,0]}><coneGeometry args={[0.9,1.15,10]}/><meshStandardMaterial color="#315a43" roughness={0.86} transparent opacity={o}/></mesh>
  <mesh position={[0,0.18,1.7]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[0.26,0.34,24]}/><meshBasicMaterial color={selected?"#86efac":"#3f6d56"} transparent opacity={0.75}/></mesh>
 </group>;
}
