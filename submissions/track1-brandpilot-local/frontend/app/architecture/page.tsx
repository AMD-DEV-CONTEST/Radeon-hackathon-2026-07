import {Icon} from "@/components/icons";
import {AnimatedSection,Surface} from "@/components/primitives";
import {SectionHeading,StatusBadge} from "@/components/ui";

const workflow=[
  {icon:"upload" as const,title:"Private asset intake",copy:"A rights-cleared product image enters through a validated local upload.",status:"Implemented"},
  {icon:"palette" as const,title:"Campaign configuration",copy:"The studio captures audience, tone, direction, formats, and guardrails.",status:"Implemented"},
  {icon:"cpu" as const,title:"Inference contract",copy:"Mock mode is the safe default. Experimental Radeon mode is a deliberate, authenticated opt-in.",status:"Verified"},
  {icon:"image" as const,title:"Protected result",copy:"Generated assets are retrieved through authenticated requests and rendered as temporary browser blobs.",status:"Verified"},
  {icon:"review" as const,title:"Human decision",copy:"Approval, revision, or rejection is stored as part of the project record.",status:"Implemented"},
];

const facts=[
  ["Default experience","Local mock mode","verified"],
  ["Standalone SDXL on Radeon","Verified on Radeon Cloud","verified"],
  ["Authenticated loopback API","Verified on Radeon Cloud","verified"],
  ["Browser-to-Radeon public edge","Blocked by official tunnel provisioning","blocked"],
  ["Product identity preservation","Not yet validated","planned"],
];

export default function Architecture(){
  return <div className="architecture-page">
    <header className="container page-hero compact-page-hero">
      <SectionHeading eyebrow="Architecture & trust" title="A clear boundary between creative flow and experimental inference." copy="BrandPilot Local is designed so the polished product experience stays useful in mock mode while Radeon inference remains explicit, protected, and evidence-led."/>
      <div className="page-hero-aside"><StatusBadge tone="good">Mock-first architecture</StatusBadge><p>No model weights, private assets, or runtime credentials ship with the frontend.</p></div>
    </header>

    <AnimatedSection className="container architecture-flow-section">
      <div className="section-intro"><p className="eyebrow">Product flow</p><h2>From product asset to accountable decision</h2><p>Each boundary is visible. Nothing quietly switches from mock data to experimental GPU inference.</p></div>
      <ol className="architecture-flow" aria-label="BrandPilot workflow">
        {workflow.map((step,index)=><li key={step.title} className="architecture-node">
          <span className="architecture-node-number">{String(index+1).padStart(2,"0")}</span>
          <span className="architecture-node-icon"><Icon name={step.icon} width={22} height={22}/></span>
          <div><div className="architecture-node-title"><h3>{step.title}</h3><StatusBadge tone={step.status==="Verified"?"good":"neutral"}>{step.status}</StatusBadge></div><p>{step.copy}</p></div>
        </li>)}
      </ol>
    </AnimatedSection>

    <AnimatedSection className="container architecture-grid">
      <Surface className="architecture-status-card">
        <p className="eyebrow">Evidence map</p><h2>What is true today</h2>
        <dl className="fact-list">{facts.map(([label,value,status])=><div key={label}><dt>{label}</dt><dd><span>{value}</span><StatusBadge tone={status==="verified"?"good":status==="blocked"?"wait":"neutral"}>{status}</StatusBadge></dd></div>)}</dl>
      </Surface>
      <Surface className="trust-card">
        <span className="feature-icon"><Icon name="shield" width={24} height={24}/></span><p className="eyebrow">Responsible by design</p><h2>Local does not mean unchecked.</h2>
        <p>Controlled processing can reduce automatic external exposure. It does not replace copyright, trademark, product-claim, representation, or disclosure review.</p>
        <ul className="check-list"><li><Icon name="check" width={16} height={16}/> Human review is part of the workflow.</li><li><Icon name="check" width={16} height={16}/> Experimental output is labelled honestly.</li><li><Icon name="check" width={16} height={16}/> Runtime access stays in the current browser session.</li></ul>
      </Surface>
    </AnimatedSection>

    <AnimatedSection className="container limitation-band">
      <div><p className="eyebrow">Deliberate limits</p><h2>Strong foundations, narrow claims.</h2></div>
      <div className="limitation-list"><p>Permanent hosted Radeon backend <strong>Not available</strong></p><p>Packaging text and logo preservation <strong>Not validated</strong></p><p>Commercial production clearance <strong>Not completed</strong></p></div>
    </AnimatedSection>
  </div>;
}
