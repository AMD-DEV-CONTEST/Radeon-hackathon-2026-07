"use client";

import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect,useState} from "react";
import {Icon} from "@/components/icons";
import {IconButton,cx} from "@/components/primitives";

const links=[
  {href:"/",label:"Overview"},
  {href:"/studio",label:"Creative Studio"},
  {href:"/architecture",label:"Architecture"},
];

function Brand(){
  return <Link className="brand" href="/" aria-label="BrandPilot Local home"><span className="brand-mark" aria-hidden="true"><span/><span/></span><span>BrandPilot</span><strong>Local</strong></Link>;
}

export function Navigation({onNavigate,className=""}:{onNavigate?:()=>void;className?:string}){
  const pathname=usePathname();
  return <div className={cx("navlinks",className)}>{links.map(link=>{
    const active=link.href==="/" ? pathname===link.href : pathname.startsWith(link.href);
    return <Link key={link.href} href={link.href} aria-current={active?"page":undefined} onClick={onNavigate}>{link.label}</Link>;
  })}</div>;
}

export function Header(){
  const [open,setOpen]=useState(false);
  useEffect(()=>{
    if(!open)return;
    const previous=document.body.style.overflow;
    document.body.style.overflow="hidden";
    const escape=(event:KeyboardEvent)=>{if(event.key==="Escape")setOpen(false)};
    window.addEventListener("keydown",escape);
    return()=>{document.body.style.overflow=previous;window.removeEventListener("keydown",escape)};
  },[open]);
  return <header className="site-header"><nav className="container nav" aria-label="Primary navigation"><Brand/><Navigation/><Link className="button button-primary nav-cta" href="/studio">Open Studio <Icon name="arrow"/></Link><IconButton className="menu-trigger" label={open?"Close navigation":"Open navigation"} aria-expanded={open} aria-controls="mobile-navigation" onClick={()=>setOpen(value=>!value)}><Icon name={open?"close":"menu"}/></IconButton></nav><div className={cx("mobile-menu",open&&"is-open")} id="mobile-navigation" aria-hidden={!open}><button className="mobile-backdrop" aria-label="Close navigation" tabIndex={open?0:-1} onClick={()=>setOpen(false)}/><div className="mobile-drawer"><div className="mobile-drawer-top"><span>Navigate</span><IconButton label="Close navigation" onClick={()=>setOpen(false)}><Icon name="close"/></IconButton></div><Navigation className="mobile-navlinks" onNavigate={()=>setOpen(false)}/><div className="mobile-menu-note"><span className="status-dot status-dot-warning"/><div><strong>Mock workspace ready</strong><span>Radeon browser edge awaits official DNS resolution.</span></div></div><Link className="button button-primary button-block" href="/studio" onClick={()=>setOpen(false)}>Open Creative Studio <Icon name="arrow"/></Link></div></div></header>;
}

export function Footer(){
  return <footer className="site-footer"><div className="container footer-grid"><div className="footer-brand"><Brand/><p>Private, review-first multimodal campaign creation on a verified AMD Radeon foundation.</p></div><div><h2>Explore</h2><Navigation className="footer-links"/></div><div><h2>Project status</h2><p><span className="status-dot status-dot-good"/>Mock mode available</p><p><span className="status-dot status-dot-warning"/>Experimental path opt-in</p><p className="footer-meta">AMD AI DevMaster Hackathon · Track 1</p></div></div><div className="container footer-bottom"><span>BrandPilot Local</span><span>Generated concepts require human review.</span></div></footer>;
}

export function PageContainer({children,className=""}:{children:React.ReactNode;className?:string}){
  return <div className={cx("container",className)}>{children}</div>;
}
