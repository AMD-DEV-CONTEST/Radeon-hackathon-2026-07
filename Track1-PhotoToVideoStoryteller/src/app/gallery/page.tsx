"use client";

import { useState, useEffect, useCallback } from "react";
import { Header } from "@/components/Header";
import { Gallery } from "@/components/Gallery";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Sparkles, Image, Download, Trash2, Filter } from "lucide-react";

interface GalleryImage {
  id: number;
  prompt: string;
  negativePrompt?: string;
  style: string;
  mode: string;
  imageUrl?: string;
  thumbnailUrl?: string;
  width: number;
  height: number;
  seed: number;
  steps: number;
  createdAt: string;
  isPublic: boolean;
}

export default function GalleryPage() {
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedStyle, setSelectedStyle] = useState("all");
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchImages = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/gallery");
      const data = await response.json();
      setImages(data.images || []);
    } catch (error) {
      console.error("Failed to fetch images:", error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchImages();
  }, [fetchImages]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await fetchImages();
    setIsRefreshing(false);
  };

  const handleDelete = async (id: number) => {
    try {
      await fetch(`/api/gallery?id=${id}`, { method: "DELETE" });
      setImages((prev) => prev.filter((img) => img.id !== id));
    } catch (error) {
      console.error("Failed to delete:", error);
    }
  };

  const handleDownload = (url: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = `neuralforge-${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const filteredImages = images.filter((img) => {
    const matchesSearch =
      !searchQuery ||
      img.prompt.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStyle =
      selectedStyle === "all" || img.style === selectedStyle;
    return matchesSearch && matchesStyle;
  });

  const styles = [
    { value: "all", label: "All Styles" },
    { value: "realistic", label: "Photorealistic" },
    { value: "anime", label: "Anime" },
    { value: "digital-art", label: "Digital Art" },
    { value: "cyberpunk", label: "Cyberpunk" },
    { value: "fantasy", label: "Fantasy" },
    { value: "minimalist", label: "Minimalist" },
    { value: "oil-painting", label: "Oil Painting" },
    { value: "watercolor", label: "Watercolor" },
    { value: "vintage", label: "Vintage" },
    { value: "abstract", label: "Abstract" },
    { value: "3d-render", label: "3D Render" },
    { value: "sketch", label: "Sketch" },
  ];

  return (
    <div className="min-h-screen bg-[#0a0a1a]">
      <Header />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold text-slate-100 flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-pink-500 flex items-center justify-center">
                <Image className="w-5 h-5 text-white" />
              </div>
              Gallery
            </h1>
            <p className="mt-1 text-slate-400">
              Your AI-generated creations
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={handleRefresh} isLoading={isRefreshing}>
              <Sparkles className="w-4 h-4 mr-2" />
              Refresh
            </Button>
          </div>
        </div>

        {/* Filters */}
        <Card className="mb-6">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <Input
                placeholder="Search generations..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="w-full sm:w-48">
              <Select
                options={styles}
                value={selectedStyle}
                onChange={(e) => setSelectedStyle(e.target.value)}
                label="Filter by Style"
              />
            </div>
          </div>
          {(searchQuery || selectedStyle !== "all") && (
            <div className="mt-3 flex items-center gap-2 text-sm text-slate-400">
              <Filter className="w-4 h-4" />
              <span>
                {filteredImages.length} of {images.length} generations
                {searchQuery && ` matching "${searchQuery}"`}
                {selectedStyle !== "all" && ` in ${selectedStyle}`}
              </span>
              <button
                onClick={() => {
                  setSearchQuery("");
                  setSelectedStyle("all");
                }}
                className="ml-auto text-indigo-400 hover:text-indigo-300"
              >
                Clear filters
              </button>
            </div>
          )}
        </Card>

        {/* Gallery Grid */}
        <Gallery
          images={filteredImages}
          isLoading={isLoading}
          onDelete={handleDelete}
          onDownload={handleDownload}
          emptyMessage="No generations found"
        />

        {/* Stats */}
        {images.length > 0 && (
          <Card className="mt-8">
            <h3 className="text-sm font-medium text-slate-300 mb-4">
              Collection Statistics
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div>
                <p className="text-2xl font-bold text-slate-100">{images.length}</p>
                <p className="text-sm text-slate-400">Total Images</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-100">
                  {new Set(images.map((i) => i.style)).size}
                </p>
                <p className="text-sm text-slate-400">Unique Styles</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-100">
                  {Math.round(images.reduce((acc, img) => acc + img.seed, 0) / images.length)}
                </p>
                <p className="text-sm text-slate-400">Avg Seed</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-100">
                  {images.reduce((acc, img) => acc + img.steps, 0) / images.length}
                </p>
                <p className="text-sm text-slate-400">Avg Steps</p>
              </div>
            </div>
          </Card>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/50 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-sm text-slate-500">
              NeuralForge AI Studio — Your creations, powered by Radeon GPUs
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
