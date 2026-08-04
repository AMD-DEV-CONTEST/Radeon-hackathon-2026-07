import type {Metadata,Viewport} from "next";
import {Montserrat,Poppins} from "next/font/google";
import {Footer,Header} from "@/components/shell";
import "./globals.css";

const poppins=Poppins({subsets:["latin"],weight:["500","600","700"],variable:"--font-display",display:"swap"});
const montserrat=Montserrat({subsets:["latin"],weight:["400","500","600","700"],variable:"--font-body",display:"swap"});

export const metadata:Metadata={
  title:{default:"BrandPilot Local",template:"%s · BrandPilot Local"},
  description:"A private, review-first multimodal campaign creation studio built on AMD Radeon and ROCm.",
};
export const viewport:Viewport={width:"device-width",initialScale:1,themeColor:"#09090b"};

export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="en" className={`${poppins.variable} ${montserrat.variable}`}><body><a className="skip-link" href="#main-content">Skip to content</a><div className="ambient-scene" aria-hidden="true"><span/><span/><span/></div><Header/><main id="main-content" tabIndex={-1}>{children}</main><Footer/></body></html>;
}
