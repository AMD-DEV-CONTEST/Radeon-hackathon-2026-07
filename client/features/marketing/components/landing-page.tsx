import { MarketingFooter } from "@/components/layout/marketing-footer";
import { MarketingNavbar } from "@/components/layout/marketing-navbar";
import { CtaSection } from "@/features/marketing/components/cta-section";
import { FeaturesSection } from "@/features/marketing/components/features-section";
import { HeroSection } from "@/features/marketing/components/hero-section";
import { TrustSection } from "@/features/marketing/components/trust-section";
import { WorkflowSection } from "@/features/marketing/components/workflow-section";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      <MarketingNavbar />
      <main>
        <HeroSection />
        <FeaturesSection />
        <WorkflowSection />
        <TrustSection />
        <CtaSection />
      </main>
      <MarketingFooter />
    </div>
  );
}
