"use client";
import React, { createContext, useContext, useState, useEffect, useMemo } from "react";
import { useSettings } from "./SettingsContext";
import {
  AI_ROUTE_OPTIONS,
  routeKeyReady,
  routeRequiresKey,
  AiRouteOption,
  routeOptionById,
} from "@/lib/aiRouting";

interface AiRouterContextValue {
  selectedModel: string;
  selectedTopology: { sentinel: string; engineer: string; observer: string };
  activeRoute: AiRouteOption | undefined;
  changeModel: (id: string) => void;
  changeTopology: (
    topology: { sentinel: string; engineer: string; observer: string },
    name: string
  ) => void;
  allowedOptions: AiRouteOption[];
  routeWarnings: string[];
}

const AiRouterContext = createContext<AiRouterContextValue | null>(null);

export function useAiRouter() {
  const ctx = useContext(AiRouterContext);
  if (!ctx) throw new Error("useAiRouter must be used inside <AiRouterProvider>");
  return ctx;
}

export function AiRouterProvider({ children }: { children: React.ReactNode }) {
  const { networkPolicy, keyStatus } = useSettings();
  const [selectedModel, setSelectedModel] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("determinex_selected_model") || "auto";
    }
    return "auto";
  });

  const [selectedTopology, setSelectedTopology] = useState(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("determinex_selected_topology");
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch (e) {}
      }
    }
    return {
      sentinel: "determinex/planner",
      engineer: "determinex/engineer",
      observer: "determinex/observer",
    };
  });

  // Filter allowed route options based on the active network policy
  const allowedOptions = useMemo(() => {
    return AI_ROUTE_OPTIONS.filter((option) => {
      if (networkPolicy === "offline") {
        // Only allow local offline models
        return option.kind === "local" || option.kind === "auto";
      }
      if (networkPolicy === "cloaked") {
        // Block raw cloud provider calls, only allow local or masked free cloud options
        return option.kind === "local" || option.kind === "auto" || option.kind === "free_cloud";
      }
      return true; // Online mode allows everything
    });
  }, [networkPolicy]);

  const activeRoute = useMemo(() => {
    return routeOptionById(selectedModel);
  }, [selectedModel]);

  // Persistent storage updates
  useEffect(() => {
    localStorage.setItem("determinex_selected_model", selectedModel);
  }, [selectedModel]);

  useEffect(() => {
    localStorage.setItem("determinex_selected_topology", JSON.stringify(selectedTopology));
  }, [selectedTopology]);

  // Compute route warnings (key status, network policy blocks)
  const routeWarnings = useMemo(() => {
    const warnings: string[] = [];
    const isAllowed = allowedOptions.some((o) => o.id === selectedModel);
    if (!isAllowed) {
      warnings.push(
        `Selected model is blocked under the active "${networkPolicy}" network policy.`
      );
    }
    if (routeRequiresKey(selectedModel) && !routeKeyReady(selectedModel, keyStatus)) {
      warnings.push(
        `Selected cloud route "${selectedModel}" requires an API key but none is configured.`
      );
    }
    return warnings;
  }, [selectedModel, allowedOptions, networkPolicy, keyStatus]);

  const changeModel = (id: string) => {
    setSelectedModel(id);
  };

  const changeTopology = (
    topology: { sentinel: string; engineer: string; observer: string },
    name: string
  ) => {
    setSelectedTopology(topology);
    // Auto-select corresponding sentinel model or custom key
    setSelectedModel("auto");
  };

  return (
    <AiRouterContext.Provider
      value={{
        selectedModel,
        selectedTopology,
        activeRoute,
        changeModel,
        changeTopology,
        allowedOptions,
        routeWarnings,
      }}
    >
      {children}
    </AiRouterContext.Provider>
  );
}
