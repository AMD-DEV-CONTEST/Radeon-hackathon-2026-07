export function updateChoiceSelection(current:string[],next:string,single:boolean):string[]{
  if(single)return [next];
  return current.includes(next)?current.filter(value=>value!==next):[...current,next];
}
