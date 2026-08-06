"use client";

import { useState, useEffect } from "react";
import { Header } from "@/components/Header";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import {
  Sparkles,
  Camera,
  Palette,
  Brush,
  Droplets,
  Zap,
  Wand,
  Square,
  Infinity,
  Box,
  PenLine,
  Filter,
} from "lucide-react";

interface Style {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
}

const styleData: Style[] = [
  { id: "realistic", name: "Photorealistic", description: "Ultra-realistic photography style with perfect lighting and detail", category: "photography", icon: "Camera" },
  { id: "anime", name: "Anime", description: "Japanese animation aesthetic with vibrant colors and clean lines", category: "art", icon: "Sparkles" },
  { id: "digital-art", name: "Digital Art", description: "Modern digital illustration with smooth gradients and polish", category: "art", icon: "Palette" },
  { id: "oil-painting", name: "Oil Painting", description: "Classic oil painting texture with visible brushstrokes", category: "traditional", icon: "Brush" },
  { id: "watercolor", name: "Watercolor", description: "Soft watercolor wash effects with bleeding edges", category: "traditional", icon: "Droplets" },
  { id: "cyberpunk", name: "Cyberpunk", description: "Neon-lit futuristic cities with high contrast", category: "theme", icon: "Zap" },
  { id: "fantasy", name: "Fantasy", description: "Magical fantasy landscapes with ethereal lighting", category: "theme", icon: "Wand" },
  { id: "minimalist", name: "Minimalist", description: "Clean minimal design with negative space", category: "design", icon: "Square" },
  { id: "vintage", name: "Vintage", description: "Retro film photography look with grain and fade", category: "photography", icon: "Camera" },
  { id: "abstract", name: "Abstract", description: "Non-representational art with bold shapes", category: "art", icon: "Infinity" },
  { id: "3d-render", name: "3D Render", description: "High-quality 3D visualization with realistic materials", category: "digital", icon: "Box" },
  { id: "sketch", name: "Sketch", description: "Hand-drawn pencil sketch with shading", category: "traditional", icon: "PenLine" },
];

const iconMap: Record<string, typeof Camera> = {
  Camera,
  Sparkles,
  Palette,
  Brush,
  Droplets,
  Zap,
  Wand,
  Square,
  Infinity,
  Box,
  PenLine,
};

const categoryColors: Record<string, string> = {
  photography: "from-blue-500/20 to-blue-500/5",
  art: "from-purple-500/20 to-purple-500/5",
  traditional: "from-amber-500/20 to-amber-500/5",
  theme: "from-pink-500/20 to-pink-500/5",
  design: "from-cyan-500/20 to-cyan-500/5",
  digital: "from-green-500/20 to-green-500/5",
};

export default function StylesPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");

  const categories = ["all", "photography", "art", "traditional", "theme", "design", "digital"];

  const filteredStyles = styleData.filter((style) => {
    const matchesSearch = !searchQuery || style.name.toLowerCase().includes(searchQuery.toLowerCase()) || style.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCategory = selectedCategory === "all" || style.category === selectedCategory;
    return matchesSearch && matchesCategory;
  });

  return (
    <div className="min-h-screen bg-[#0a0a1a]">
      <Header />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-slate-100 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-pink-500 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            Art Styles
          </h1>
          <p className="mt-1 text-slate-400">
            Explore our collection of AI-powered artistic styles
          </p>
        </div>

        {/* Filters */}
        <Card className="mb-8">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <div className="relative">
                <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input
                  type="text"
                  placeholder="Search styles..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {categories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors capitalize ${
                    selectedCategory === cat
                      ? "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30"
                      : "bg-slate-800/50 text-slate-400 border border-slate-700/30 hover:border-slate-600/50"
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
        </Card>

        {/* Style Grid */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filteredStyles.map((style) => {
            const Icon = iconMap[style.icon] || Sparkles;
            return (
              <Card
                key={style.id}
                className="group hover:bg-slate-800/60 transition-all hover:border-indigo-500/30 cursor-pointer"
              >
                <div className={`w-full h-32 rounded-xl bg-gradient-to-br ${categoryColors[style.category] || categoryColors.art} mb-4 flex items-center justify-center overflow-hidden`}>
                  <div className="relative">
                    <Icon className="w-12 h-12 text-indigo-400/50" />
                    <div className="absolute inset-0 bg-indigo-500/5 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="font-medium text-slate-200 group-hover:text-indigo-300 transition-colors">
                      {style.name}
                    </h3>
                    <span className={`px-2 py-0.5 rounded-full text-xs bg-gradient-to-r ${categoryColors[style.category] || categoryColors.art} text-slate-400 capitalize`}>
                      {style.category}
                    </span>
                  </div>
                  <p className="text-sm text-slate-400 line-clamp-2">
                    {style.description}
                  </p>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="w-full mt-2 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Use Style
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>

        {filteredStyles.length === 0 && (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto rounded-full bg-slate-800/50 flex items-center justify-center">
              <Filter className="w-8 h-8 text-slate-500" />
            </div>
            <h3 className="mt-4 text-lg font-medium text-slate-400">
              No styles found
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              Try adjusting your search or filters
            </p>
          </div>
        )}

        {/* Info Card */}
        <Card className="mt-8">
          <h3 className="text-lg font-medium text-slate-200 mb-4 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-400" />
            About Art Styles
          </h3>
          <div className="grid sm:grid-cols-2 gap-4 text-sm text-slate-400">
            <div className="p-4 rounded-xl bg-slate-800/30 border border-slate-700/30">
              <h4 className="font-medium text-slate-300 mb-2">Style Transfer</h4>
              <p>
                Our AI can apply the visual characteristics of any style to your images, transforming photos into paintings, anime, or abstract art.
              </p>
            </div>
            <div className="p-4 rounded-xl bg-slate-800/30 border border-slate-700/30">
              <h4 className="font-medium text-slate-300 mb-2">Customization</h4>
              <p>
                Combine multiple styles and adjust parameters to create unique visual effects. Each generation can produce different variations.
              </p>
            </div>
          </div>
        </Card>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/50 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-sm text-slate-500">
              NeuralForge AI Studio — 12+ styles available
            </p>
            <Button variant="ghost" size="sm" onClick={() => window.location.href = "/"}>
              Back to Studio
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}
