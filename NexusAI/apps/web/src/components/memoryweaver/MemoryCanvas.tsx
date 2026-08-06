'use client';
import {useMemo,useState} from 'react';
import {memories} from './mockData';
import MemorySearch from './MemorySearch';
import MemoryTimeline from './MemoryTimeline';
import MemoryCard from './MemoryCard';
import MemoryInspector from './MemoryInspector';
export default function MemoryCanvas(){
const[q,setQ]=useState('');
const[selected,setSelected]=useState<any>(null);
const filtered=useMemo(()=>memories.filter(m=>(m.title+m.summary).toLowerCase().includes(q.toLowerCase())),[q]);
return <div className='grid grid-cols-3 gap-6'>
<div className='col-span-2 space-y-4'>
<MemorySearch value={q} onChange={setQ}/>
<MemoryTimeline items={filtered}/>
<div className='space-y-3'>{filtered.map(m=><MemoryCard key={m.id} memory={m} onSelect={setSelected}/>)}</div>
</div>
<div className='rounded-xl border p-4'><MemoryInspector memory={selected}/></div>
</div>;
}