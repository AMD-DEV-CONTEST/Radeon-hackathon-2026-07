'use client';
import {MemoryItem} from "./types";
export default function MemoryCard({memory,onSelect}:{memory:MemoryItem,onSelect:(m:MemoryItem)=>void}){
return <div onClick={()=>onSelect(memory)} className="cursor-pointer rounded-xl border p-4 hover:border-cyan-400"><h3>{memory.title}</h3><p>{memory.summary}</p></div>;
}