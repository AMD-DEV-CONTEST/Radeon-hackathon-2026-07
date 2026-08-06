import AnimatedBackground from "@/components/home/AnimatedBackground";
import Hero from "@/components/home/Hero";
import FeatureStrip from "@/components/home/FeatureStrip";
import WorldGrid from "@/components/home/WorldGrid";
import RadeonSection from "@/components/home/RadeonSection";
import Architecture from "@/components/home/Architecture";
import Stats from "@/components/home/Stats";
import Footer from "@/components/home/Footer";

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-x-hidden bg-[#050608] text-white">
      <AnimatedBackground />

      <div className="relative z-10">
        <Hero />

        <section className="mx-auto max-w-7xl px-6 py-12">
          <FeatureStrip />
        </section>

        <section className="mx-auto max-w-7xl px-6 py-20">
          <WorldGrid />
        </section>

        <section className="mx-auto max-w-7xl px-6 py-20">
          <Architecture />
        </section>

        <section className="mx-auto max-w-7xl px-6 py-20">
          <RadeonSection />
        </section>

        <section className="mx-auto max-w-7xl px-6 py-20">
          <Stats />
        </section>

        <Footer />
      </div>
    </main>
  );
}
