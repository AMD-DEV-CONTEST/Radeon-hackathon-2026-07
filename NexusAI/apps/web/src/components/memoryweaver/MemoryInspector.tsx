import {MemoryItem} from "./types";
export default function MemoryInspector({memory}:{memory:MemoryItem|null}){
if(!memory)return <div>Select a memory</div>;
return <div><h2>{memory.title}</h2><p>{memory.summary}</p><p>People: {memory.people.join(", ")}</p><p>Places: {memory.places.join(", ")}</p></div>;
}