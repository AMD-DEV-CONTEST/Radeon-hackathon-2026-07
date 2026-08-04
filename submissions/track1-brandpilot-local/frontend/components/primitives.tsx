"use client";

import type {ButtonHTMLAttributes,HTMLAttributes,ReactNode} from "react";

export function cx(...classes:Array<string|false|null|undefined>):string{
  return classes.filter(Boolean).join(" ");
}

export function Button({variant="secondary",loading=false,className="",children,disabled,...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:"primary"|"secondary"|"ghost"|"subtle"|"danger";loading?:boolean}){
  return <button className={cx("button",`button-${variant}`,className)} disabled={disabled||loading} aria-busy={loading||undefined} {...props}>{loading&&<span className="button-spinner" aria-hidden="true"/>}{children}</button>;
}

export function IconButton({label,className="",children,...props}:ButtonHTMLAttributes<HTMLButtonElement>&{label:string;children:ReactNode}){
  return <button className={cx("icon-button",className)} aria-label={label} title={label} {...props}>{children}</button>;
}

export function Surface({as="section",className="",children,...props}:{as?:"section"|"article"|"div"|"aside";children:ReactNode}&HTMLAttributes<HTMLElement>){
  const Component=as;
  return <Component className={cx("surface",className)} {...props}>{children}</Component>;
}

export function AnimatedSection({className="",children,...props}:HTMLAttributes<HTMLElement>){
  return <section className={cx("reveal-section",className)} {...props}>{children}</section>;
}

export function FormField({htmlFor,label,hint,error,children,className=""}:{htmlFor:string;label:string;hint?:string;error?:string;children:ReactNode;className?:string}){
  const hintId=hint?`${htmlFor}-hint`:undefined;
  const errorId=error?`${htmlFor}-error`:undefined;
  return <div className={cx("field",className)}><label htmlFor={htmlFor}>{label}</label>{hint&&<p className="field-hint" id={hintId}>{hint}</p>}{children}{error&&<p className="field-error" id={errorId} role="alert">{error}</p>}</div>;
}

export function FormSection({number,title,description,children,className=""}:{number:string;title:string;description:string;children:ReactNode;className?:string}){
  return <section className={cx("form-section",className)}><header className="form-section-header"><span className="section-index" aria-hidden="true">{number}</span><div><h2>{title}</h2><p>{description}</p></div></header><div className="form-section-body">{children}</div></section>;
}
