import type {CampaignResult,Project,ProjectConfig,SystemInfo} from "./types";
export const API=process.env.NEXT_PUBLIC_API_BASE_URL||"http://localhost:8000";
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API}${path}`,init);if(!response.ok){let message=`Request failed (${response.status})`;try{const body=await response.json();message=body.detail?.message||body.detail||message}catch{}throw new Error(message)}return response.json()}
export const api={
 health:()=>request<{status:string}>("/health"),
 system:()=>request<SystemInfo>("/system-info"),
 create:(configuration:ProjectConfig)=>request<Project>("/projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(configuration)}),
 upload:(id:string,file:File)=>{const body=new FormData();body.append("file",file);return request<Project["asset"]>(`/projects/${id}/assets`,{method:"POST",body})},
 get:(id:string)=>request<Project>(`/projects/${id}`),
 generate:(id:string)=>request<{results:CampaignResult[]}>(`/projects/${id}/generate`,{method:"POST"}),
 review:(id:string,rid:string,status:string,note="")=>request<CampaignResult>(`/projects/${id}/results/${rid}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,note})}),
 edit:(id:string,rid:string,data:Partial<CampaignResult>)=>request<CampaignResult>(`/projects/${id}/results/${rid}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)}),
 regenerate:(id:string,rid:string)=>request<CampaignResult>(`/projects/${id}/results/${rid}/regenerate`,{method:"POST"})
};
