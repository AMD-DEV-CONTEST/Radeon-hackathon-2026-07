import type { Projection } from "../types";
import { BookIcon, ChipIcon, CloseIcon, DocumentIcon, MenuIcon, ReceiptIcon, ShieldIcon } from "./Icons";
import { displayCompany } from "../format";

type Props = {
  projection: Projection;
  activeSection: string;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onSection: (id: string) => void;
};

export function MobileHeader({ onOpen }: Pick<Props, "onOpen">) {
  return (
    <header className="mobile-header">
      <button className="icon-button" onClick={onOpen} aria-label="Open research navigation"><MenuIcon /></button>
      <Brand compact />
      <span className="local-dot" aria-label="Local model connected" />
    </header>
  );
}

export function Navigation({ projection, activeSection, open, onClose, onSection }: Props) {
  return (
    <>
      <button className={`nav-scrim ${open ? "is-open" : ""}`} onClick={onClose} aria-label="Close navigation" tabIndex={open ? 0 : -1} />
      <aside className={`side-nav ${open ? "is-open" : ""}`} aria-label="Research case navigation">
        <div className="nav-brand-row">
          <Brand />
          <button className="icon-button nav-close" onClick={onClose} aria-label="Close navigation"><CloseIcon /></button>
        </div>
        <div className="case-marker">
          <span>Active research case</span>
          <strong>{projection.companies.map((company) => displayCompany(company.label)).join(" / ")}</strong>
          <small>As of {formatDate(projection.as_of)}</small>
        </div>
        <nav className="section-links" aria-label="Analysis sections">
          {projection.sections.map((section, index) => (
            <button
              key={section.section_type}
              className={activeSection === section.section_type ? "active" : ""}
              onClick={() => { onSection(section.section_type); onClose(); }}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>{section.title}
            </button>
          ))}
        </nav>
        <div className="nav-proof-grid" aria-label="Case proof summary">
          <div><DocumentIcon /><strong>{projection.evidence.length}</strong><span>sources</span></div>
          <div><ReceiptIcon /><strong>{projection.calculations.length}</strong><span>receipts</span></div>
          <div><ShieldIcon /><strong>{Math.round(projection.metrics.evidence_coverage * 100)}%</strong><span>coverage</span></div>
          <div><ChipIcon /><strong>{projection.metrics.model_calls}</strong><span>local calls</span></div>
        </div>
        <div className="privacy-stamp">
          <ShieldIcon />
          <div><strong>Private by architecture</strong><span>Loopback-only inference</span></div>
        </div>
      </aside>
    </>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? "compact" : ""}`} aria-label="SignalForge">
      <span className="brand-mark"><BookIcon /></span>
      <span><strong>SignalForge</strong>{!compact && <small>Investor intelligence, forged locally</small>}</span>
    </div>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(value));
}
