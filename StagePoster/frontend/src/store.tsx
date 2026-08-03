import {createContext,useCallback,useContext,useEffect,useMemo,useState,type ReactNode} from 'react';
import type {GenerationTask,PosterProject} from './types';
import {demoProject} from './data/mock';

interface Store{projects:Record<string,PosterProject>;tasks:Record<string,GenerationTask>;save:(p:PosterProject)=>void;saveTask:(t:GenerationTask)=>void}
interface StoreState{projects:Record<string,PosterProject>;tasks:Record<string,GenerationTask>}
const KEY='poster-mvp-state-v1';
const Context=createContext<Store|null>(null);

export function StoreProvider({children}:{children:ReactNode}){
 const[state,setState]=useState<StoreState>(()=>{try{return JSON.parse(localStorage.getItem(KEY)??'') as StoreState}catch{return{projects:{'demo-changan':demoProject()},tasks:{}}}});
 useEffect(()=>{try{localStorage.setItem(KEY,JSON.stringify(state))}catch(error){console.error('项目本地保存失败',error)}},[state]);
 const save=useCallback((project:PosterProject)=>setState(current=>({...current,projects:{...current.projects,[project.id]:project}})),[]);
 const saveTask=useCallback((task:GenerationTask)=>setState(current=>({...current,tasks:{...current.tasks,[task.id]:task}})),[]);
 const value=useMemo<Store>(()=>({...state,save,saveTask}),[state,save,saveTask]);
 return <Context.Provider value={value}>{children}</Context.Provider>;
}

export const useStore=()=>{const value=useContext(Context);if(!value)throw new Error('StoreProvider missing');return value};
