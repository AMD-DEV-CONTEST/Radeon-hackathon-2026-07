"use client";

import { motion, useScroll, useTransform } from "framer-motion";

export default function Hero() {
  const { scrollY } = useScroll();

  const opacity = useTransform(scrollY, [0, 700], [1, 0]);

  return (
    <section className="relative flex h-screen items-center justify-center overflow-hidden">
      {/* Background Video */}

      <motion.video
        autoPlay
        muted
        loop
        playsInline
        style={{ opacity }}
        className="absolute inset-0 h-full w-full object-cover"
      >
        <source src="/videos/hero.mp4" type="video/mp4" />
      </motion.video>

      {/* Dark Overlay */}

      <div className="absolute inset-0 bg-[#050608]/55" />

      {/* Gradient */}

      <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-[#050608]/45 to-[#050608]" />

      {/* Center */}

      <div className="relative z-20 flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center text-center">
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mb-6 tracking-[12px] text-[#CFA86B]"
          >
            HOPE404
          </motion.p>

          <motion.h1
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1 }}
            className="
        bg-gradient-to-r
        from-[#6E5430]
        via-[#FFF5D6]
        to-[#D5A14C]
        bg-clip-text
        text-transparent
        font-black
        tracking-[-0.06em]
        leading-none
        text-[6rem]
        sm:text-[8rem]
        md:text-[10rem]
        lg:text-[12rem]
        xl:text-[13rem]
        drop-shadow-[0_0_35px_rgba(255,235,180,0.15)]
        select-none
    "
          >
            NEXUS AI
          </motion.h1>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4 }}
            className="mt-8 text-3xl text-[#E8DEC9]"
          >
            Build Worlds from Knowledge.
          </motion.p>
        </div>
      </div>

      {/* Scroll Hint */}

      <motion.div
        animate={{
          y: [0, 12, 0],
        }}
        transition={{
          repeat: Infinity,
          duration: 2,
        }}
        className="absolute bottom-12 left-1/2 z-30 -translate-x-1/2 text-[#CFA86B]/70"
      >
        ↓ Scroll to Enter
      </motion.div>
    </section>
  );
}
