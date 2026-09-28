import Link from "next/link";
import {Icon} from "@/components/icons";

export default function NotFound(){
  return <div className="container not-found">
    <div className="not-found-art" aria-hidden="true"><span className="orbit orbit-one"/><span className="orbit orbit-two"/><span className="lost-card"><Icon name="sparkles" width={28} height={28}/><b>404</b></span></div>
    <div className="not-found-copy"><p className="eyebrow">Lost concept · 404</p><h1>This direction is not on the board.</h1><p className="lead">The page may have moved, but your campaign workspace is one decision away.</p><div className="actions"><Link className="button button-primary" href="/">Return home <Icon name="arrow" width={17} height={17}/></Link><Link className="button button-secondary" href="/studio">Open Creative Studio</Link></div></div>
  </div>;
}
