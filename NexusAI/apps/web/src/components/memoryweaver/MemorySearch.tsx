'use client';
export default function MemorySearch({value,onChange}:{value:string,onChange:(v:string)=>void}){
return <input className="w-full rounded-xl border p-3 bg-black/30" placeholder="Search memories..." value={value} onChange={e=>onChange(e.target.value)}/>;
}