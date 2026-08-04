"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import {
  Home,
  LayoutDashboard,
  Database,
  Activity,
  ShoppingBag,
  Rocket,
  X,
  Sparkles,
  Compass,
} from "lucide-react";
import { useLaunchStore } from "@/stores/launchStore";
import axios from "axios";

gsap.registerPlugin(useGSAP);

interface RadialMenuItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  path?: string;
  action?: () => void;
  color: string;
  glowColor: string;
}

export const RadialMenu: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const { setCurrentLaunchId, setStatus } = useLaunchStore();

  const containerRef = useRef<HTMLDivElement>(null);
  const tlRef = useRef<gsap.core.Timeline | null>(null);

  const handleQuickLaunch = async () => {
    setIsLaunching(true);
    setStatus("running");
    setIsOpen(false);

    if (pathname !== "/dashboard") {
      router.push("/dashboard");
    }

    try {
      const mockProductId = "123e4567-e89b-12d3-a456-426614174000";
      const res = await axios.post(
        "http://localhost:8000/api/v1/launches",
        {
          product_id: mockProductId,
          target_marketplaces: ["amazon", "shopify"],
          preferences: {},
        },
        {
          headers: {
            Authorization: "Bearer mock_token_for_hackathon",
          },
        }
      );
      if (res.data && res.data.id) {
        setCurrentLaunchId(res.data.id);
      }
    } catch (error) {
      console.error("Quick launch failed:", error);
    } finally {
      setIsLaunching(false);
    }
  };

  const menuItems: RadialMenuItem[] = [
    {
      id: "home",
      label: "Welcome Home",
      icon: <Home className="w-5 h-5" />,
      path: "/",
      color: "from-blue-600 to-indigo-600",
      glowColor: "rgba(79, 70, 229, 0.6)",
    },
    {
      id: "dashboard",
      label: "Orchestration Dashboard",
      icon: <LayoutDashboard className="w-5 h-5" />,
      path: "/dashboard",
      color: "from-purple-600 to-pink-600",
      glowColor: "rgba(168, 85, 247, 0.6)",
    },
    {
      id: "memory",
      label: "Chroma Vector Memory",
      icon: <Database className="w-5 h-5" />,
      path: "/memory",
      color: "from-emerald-600 to-teal-600",
      glowColor: "rgba(16, 185, 129, 0.6)",
    },
    {
      id: "benchmark",
      label: "ROCm Benchmarks",
      icon: <Activity className="w-5 h-5" />,
      path: "/benchmark",
      color: "from-amber-600 to-orange-600",
      glowColor: "rgba(245, 158, 11, 0.6)",
    },
    {
      id: "marketplace",
      label: "Marketplace Exporter",
      icon: <ShoppingBag className="w-5 h-5" />,
      path: "/marketplace",
      color: "from-cyan-600 to-blue-600",
      glowColor: "rgba(6, 182, 212, 0.6)",
    },
    {
      id: "launch",
      label: isLaunching ? "Launching Agents..." : "Quick Launch AI Team",
      icon: <Rocket className={`w-5 h-5 ${isLaunching ? "animate-bounce" : ""}`} />,
      action: handleQuickLaunch,
      color: "from-[#ED1C24] to-[#9B111E]",
      glowColor: "rgba(237, 28, 36, 0.8)",
    },
  ];

  // Calculate coordinates along a 90-degree quadrant arc (180 deg to 270 deg)
  const getCoordinates = (index: number, total: number) => {
    const startAngle = 180; // Directly Left
    const endAngle = 270;   // Directly Up
    const angleStep = (endAngle - startAngle) / (total - 1);
    const currentAngleDeg = startAngle + index * angleStep;
    const currentAngleRad = (currentAngleDeg * Math.PI) / 180;
    const radius = 145;

    const x = Math.round(radius * Math.cos(currentAngleRad));
    const y = Math.round(radius * Math.sin(currentAngleRad));

    return { x, y };
  };

  // GSAP Interruptible Single Timeline Enter/Exit Choreography
  useGSAP(() => {
    const tl = gsap.timeline({
      paused: true,
      defaults: { ease: "power3.out" },
    });

    // 0. Ensure initial hidden state & enable interactivity when playing forward past time 0.01
    tl.set(".radial-backdrop", { pointerEvents: "auto", display: "block" }, 0.01)
      .set(".radial-item", { pointerEvents: "auto" }, 0.01);

    // 1. Fade in backdrop overlay
    tl.to(".radial-backdrop", { opacity: 1, duration: 0.35, ease: "power2.inOut" }, 0);

    // 2. Animate central toggle icon (Compass exits, X enters)
    tl.to(".toggle-compass", { rotate: 180, scale: 0.5, opacity: 0, duration: 0.25, ease: "power2.in" }, 0)
      .fromTo(".toggle-close", 
        { rotate: -180, scale: 0.5, opacity: 0 }, 
        { rotate: 0, scale: 1, opacity: 1, duration: 0.35, ease: "back.out(1.7)" }, 
        0.08
      );

    // 3. Expand satellite items along radial arc with staggered elastic bounce
    tl.fromTo(
      ".radial-item",
      { x: 0, y: 0, scale: 0, opacity: 0, rotate: -75 },
      {
        x: (index, target) => parseFloat(target.getAttribute("data-x") || "0"),
        y: (index, target) => parseFloat(target.getAttribute("data-y") || "0"),
        scale: 1,
        opacity: 1,
        rotate: 0,
        duration: 0.55,
        stagger: 0.05,
        ease: "back.out(1.8)",
      },
      0.08
    );

    // 4. When reversed fully to 0, disable pointer events
    tl.eventCallback("onReverseComplete", () => {
      gsap.set(".radial-backdrop", { pointerEvents: "none", display: "none" });
      gsap.set(".radial-item", { pointerEvents: "none" });
    });

    tlRef.current = tl;
  }, { scope: containerRef });

  // Play or reverse the SINGLE interruptible timeline when isOpen changes
  useEffect(() => {
    if (!tlRef.current) return;
    if (isOpen) {
      // Plays forward from any intermediate progress point if interrupted!
      tlRef.current.play();
    } else {
      // Reverses smoothly from any intermediate progress point if interrupted!
      tlRef.current.reverse();
    }
  }, [isOpen]);

  const handleItemClick = (item: RadialMenuItem) => {
    if (item.action) {
      item.action();
    } else if (item.path) {
      router.push(item.path);
      setIsOpen(false);
    }
  };

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div ref={containerRef}>
      {/* Backdrop overlay (managed by GSAP timeline) */}
      <div
        onClick={() => setIsOpen(false)}
        className="radial-backdrop fixed inset-0 bg-black/50 backdrop-blur-[3px] z-40 opacity-0 hidden pointer-events-none transition-none"
      />

      {/* Radial Menu Container */}
      <div className="fixed bottom-8 right-8 z-50 flex items-center justify-center">
        {/* Satellite Menu Items */}
        {menuItems.map((item, idx) => {
          const { x, y } = getCoordinates(idx, menuItems.length);
          const isActive = pathname === item.path;

          return (
            <div
              key={item.id}
              data-x={x}
              data-y={y}
              className="radial-item absolute pointer-events-none opacity-0 scale-0"
              style={{ transform: "translate(0px, 0px)" }}
            >
              <button
                onClick={() => handleItemClick(item)}
                style={{
                  boxShadow: isOpen ? `0 0 20px ${item.glowColor}` : "none",
                }}
                className={`group relative w-12 h-12 rounded-full bg-gradient-to-tr ${item.color} p-[2px] flex items-center justify-center text-white transition-transform duration-200 hover:scale-115 active:scale-95 cursor-pointer border border-white/25`}
                title={item.label}
              >
                <div className="w-full h-full rounded-full bg-neutral-950/85 backdrop-blur-md flex items-center justify-center group-hover:bg-transparent transition-colors duration-300">
                  {item.icon}
                </div>

                {/* Tooltip Label */}
                <span className="absolute whitespace-nowrap px-3 py-1 rounded-lg bg-neutral-900/95 border border-white/15 text-xs font-semibold tracking-wide text-gray-100 pointer-events-none -top-10 shadow-[0_4px_12px_rgba(0,0,0,0.5)] opacity-0 group-hover:opacity-100 transition-all duration-200 transform translate-y-1 group-hover:translate-y-0 z-50 flex items-center gap-1.5">
                  {item.id === "launch" && <Sparkles className="w-3 h-3 text-amber-400 animate-spin" />}
                  {item.label}
                  {isActive && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block ml-1" />}
                </span>
              </button>
            </div>
          );
        })}

        {/* Central Toggle Button */}
        <div className="relative">
          {/* Subtle pulse ring when closed */}
          {!isOpen && (
            <span className="absolute inset-0 rounded-full bg-[#ED1C24]/40 animate-ping pointer-events-none" />
          )}

          <button
            onClick={() => setIsOpen(!isOpen)}
            style={{
              boxShadow: isOpen
                ? "0 0 35px rgba(237, 28, 36, 0.95)"
                : "0 0 20px rgba(237, 28, 36, 0.6)",
            }}
            className="relative w-[60px] h-[60px] rounded-full bg-gradient-to-tr from-[#ED1C24] via-[#C9181F] to-[#800F14] border-2 border-white/30 flex items-center justify-center text-white cursor-pointer z-50 hover:scale-105 active:scale-95 transition-all duration-300 group overflow-hidden"
          >
            {/* Open Icon (Compass) */}
            <div className="toggle-compass absolute inset-0 flex items-center justify-center">
              <Compass className="w-7 h-7 text-white group-hover:rotate-45 transition-transform duration-300" />
            </div>

            {/* Close Icon (X) */}
            <div className="toggle-close absolute inset-0 flex items-center justify-center opacity-0 scale-50 -rotate-180">
              <X className="w-7 h-7 text-white" />
            </div>

            {/* Tooltip for toggle when closed */}
            {!isOpen && (
              <span className="absolute whitespace-nowrap px-3 py-1 rounded-lg bg-neutral-900/95 border border-[#ED1C24]/30 text-xs font-semibold tracking-wide text-gray-100 pointer-events-none -left-36 shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[#ED1C24] animate-pulse" />
                GSAP Radial Menu
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
