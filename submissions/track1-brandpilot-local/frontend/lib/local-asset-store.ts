export const DRAFT_ASSET_WORKSPACE="studio-draft";
export const MAX_PRODUCT_IMAGE_SIZE=10*1024*1024;

const DATABASE_NAME="brandpilot-local-assets";
const DATABASE_VERSION=1;
const STORE_NAME="draft-assets";
const ALLOWED_EXTENSIONS:Record<string,Set<string>>={
  "image/png":new Set(["png"]),
  "image/jpeg":new Set(["jpg","jpeg"]),
  "image/webp":new Set(["webp"]),
};

type StoredAsset={
  workspaceId:string;
  blob:Blob;
  filename:string;
  mimeType:string;
  size:number;
  lastModified:number;
};

export function validateProductImage(file:Pick<File,"name"|"type"|"size">):string|null{
  const allowed=ALLOWED_EXTENSIONS[file.type];
  if(!allowed)return "Choose a PNG, JPEG, or WebP image.";
  const extension=file.name.toLowerCase().split(".").pop()||"";
  if(!allowed.has(extension))return "The filename extension does not match the image type.";
  if(file.size>MAX_PRODUCT_IMAGE_SIZE)return "Image must be 10 MB or smaller.";
  if(file.size===0)return "Choose a non-empty image file.";
  return null;
}

export function createPreviewObjectUrl(blob:Blob,urlApi:Pick<typeof URL,"createObjectURL"|"revokeObjectURL">=URL){
  const url=urlApi.createObjectURL(blob);
  let revoked=false;
  return {url,revoke:()=>{if(!revoked){revoked=true;urlApi.revokeObjectURL(url)}}};
}

function requestResult<T>(request:IDBRequest<T>):Promise<T>{
  return new Promise((resolve,reject)=>{
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(new Error("Local image storage request failed."));
  });
}

function openDatabase():Promise<IDBDatabase>{
  if(typeof indexedDB==="undefined")return Promise.reject(new Error("Local image storage is unavailable."));
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open(DATABASE_NAME,DATABASE_VERSION);
    request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains(STORE_NAME))request.result.createObjectStore(STORE_NAME,{keyPath:"workspaceId"})};
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(new Error("Local image storage could not be opened."));
  });
}

export async function saveDraftAsset(file:File):Promise<void>{
  const validation=validateProductImage(file);
  if(validation)throw new Error(validation);
  const database=await openDatabase();
  try{
    const transaction=database.transaction(STORE_NAME,"readwrite");
    const record:StoredAsset={workspaceId:DRAFT_ASSET_WORKSPACE,blob:file.slice(0,file.size,file.type),filename:file.name,mimeType:file.type,size:file.size,lastModified:file.lastModified};
    await requestResult(transaction.objectStore(STORE_NAME).put(record));
  }finally{database.close()}
}

export async function loadDraftAsset():Promise<File|null>{
  const database=await openDatabase();
  try{
    const transaction=database.transaction(STORE_NAME,"readonly");
    const record=await requestResult(transaction.objectStore(STORE_NAME).get(DRAFT_ASSET_WORKSPACE)) as StoredAsset|undefined;
    if(!record)return null;
    const validation=validateProductImage({name:record.filename,type:record.mimeType,size:record.size});
    if(validation||!(record.blob instanceof Blob)||record.blob.size!==record.size){await clearDraftAsset();return null}
    return new File([record.blob],record.filename,{type:record.mimeType,lastModified:record.lastModified});
  }finally{database.close()}
}

export async function clearDraftAsset():Promise<void>{
  const database=await openDatabase();
  try{
    const transaction=database.transaction(STORE_NAME,"readwrite");
    await requestResult(transaction.objectStore(STORE_NAME).delete(DRAFT_ASSET_WORKSPACE));
  }finally{database.close()}
}
