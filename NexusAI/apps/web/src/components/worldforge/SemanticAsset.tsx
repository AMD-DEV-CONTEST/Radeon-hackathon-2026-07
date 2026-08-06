"use client";
import { Clone, useGLTF } from "@react-three/drei";
import type { EntityKind } from "./types";
import { getWorldAsset } from "./AssetRegistry";

function LoadedAsset({url,scale,yOffset,rotationY=0}:{url:string;scale:number;yOffset:number;rotationY?:number}){
 const gltf=useGLTF(url);
 return <group position={[0,yOffset,0]} rotation={[0,rotationY,0]} scale={scale}><Clone object={gltf.scene} castShadow receiveShadow/></group>;
}
export default function SemanticAsset({kind,fallback}:{kind:EntityKind;fallback:React.ReactNode}){
 const asset=getWorldAsset(kind);
 return asset?<LoadedAsset url={asset.url} scale={asset.scale} yOffset={asset.yOffset} rotationY={asset.rotationY}/>:<>{fallback}</>;
}
