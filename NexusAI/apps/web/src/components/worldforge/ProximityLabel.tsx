"use client";
import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Vec3 } from "./types";

export default function ProximityLabel({position,children,near=5,far=16,worldFar=28,major=false}:{position:Vec3;children:React.ReactNode;near?:number;far?:number;worldFar?:number;major?:boolean}) {
 const ref=useRef<HTMLDivElement>(null);
 useFrame(({camera})=>{
   if(!ref.current)return;
   const d=camera.position.distanceTo({x:position[0],y:position[1],z:position[2]} as any);
   const max=major?worldFar:far;
   const opacity=d<=near?1:d>=max?0:1-(d-near)/(max-near);
   ref.current.style.opacity=String(opacity);
   ref.current.style.transform=`scale(${0.92+opacity*0.08})`;
   ref.current.style.pointerEvents=opacity>0.65?"auto":"none";
 });
 return <Html position={position} center distanceFactor={20} zIndexRange={[20,0]}>
   <div ref={ref} style={{opacity:0,transition:"opacity 180ms ease, transform 180ms ease",willChange:"opacity, transform"}}>{children}</div>
 </Html>;
}
