"use client";

import { useState, useEffect } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  Image,
  Search,
  Filter,
  Grid,
  List,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Clock,
  Download,
  Trash2,
} from "lucide-react";

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

interface GalleryProps {
  images?: GalleryImage[];
  isLoading?: boolean;
  onDelete?: (id: number) => Promise<void>;
  onDownload?: (url: string) => void;
  emptyMessage?: string;
}

const styleLabels: Record<string, string> = {
  realistic: "Photorealistic",
  anime: "Anime",
  "digital-art": "Digital Art",
  "oil-painting": "Oil Painting",
  watercolor: "Watercolor",
  cyberpunk: "Cyberpunk",
  fantasy: "Fantasy",
  minimalist: "Minimalist",
  vintage: "Vintage",
  abstract: "Abstract",
  "3d-render": "3D Render",
  sketch: "Sketch",
};

export function Gallery({
  images = [],
  isLoading = false,
  onDelete,
  onDownload,
  emptyMessage = "No generations yet",
}: GalleryProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedStyle, setSelectedStyle] = useState<string>("all");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<number | null>(null);

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
  ];

  const handleDelete = async (id: number) => {
    if (onDelete) {
      await onDelete(id);
    }
    setShowDeleteConfirm(null);
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Card key={i} className="animate-pulse">
              <div className="aspect-square bg-slate-700/30 rounded-lg" />
              <div className="mt-3 space-y-2">
                <div className="h-4 bg-slate-700/30 rounded w-3/4" />
                <div className="h-3 bg-slate-700/20 rounded w-1/2" />
              </div>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (filteredImages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-16 h-16 rounded-full bg-slate-800/50 flex items-center justify-center">
          <Image className="w-8 h-8 text-slate-500" />
        </div>
        <h3 className="mt-4 text-lg font-medium text-slate-400">
          {emptyMessage}
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Generate your first image to see it here
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search generations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
        </div>
        <div className="flex gap-2">
          <select
            value={selectedStyle}
            onChange={(e) => setSelectedStyle(e.target.value)}
            className="px-3 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-xl text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 cursor-pointer"
          >
            {styles.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <div className="flex border border-slate-700/50 rounded-xl overflow-hidden">
            <button
              onClick={() => setViewMode("grid")}
              className={`p-2.5 ${viewMode === "grid" ? "bg-indigo-500/20 text-indigo-400" : "bg-slate-800/50 text-slate-400 hover:text-slate-200"}`}
            >
              <Grid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode("list")}
              className={`p-2.5 ${viewMode === "list" ? "bg-indigo-500/20 text-indigo-400" : "bg-slate-800/50 text-slate-400 hover:text-slate-200"}`}
            >
              <List className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Gallery Grid/List */}
      {viewMode === "grid" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredImages.map((img) => (
            <Card key={img.id} className="group hover:bg-slate-800/60 transition-colors">
              <div className="relative aspect-square bg-slate-900/50 rounded-lg overflow-hidden mb-3">
                {img.imageUrl ? (
                  <img
                    src={img.imageUrl}
                    alt={img.prompt}
                    className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <Image className="w-12 h-12 text-slate-600" />
                  </div>
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-3">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onDownload?.(img.imageUrl || "")}
                    disabled={!img.imageUrl}
                    className="w-full gap-1.5"
                  >
                    <Download className="w-4 h-4" />
                    Download
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-slate-300 line-clamp-2">
                  {img.prompt}
                </p>
                <div className="flex items-center justify-between">
                  <span className="px-2 py-0.5 bg-slate-700/30 rounded-full text-xs text-slate-400 capitalize">
                    {styleLabels[img.style] || img.style}
                  </span>
                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock className="w-3 h-3" />
                    {new Date(img.createdAt).toLocaleDateString()}
                  </div>
                </div>
              </div>
              {onDelete && (
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setShowDeleteConfirm(img.id)}
                    className="p-1.5 -translate-y-1/2 text-slate-400 hover:text-red-400"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {filteredImages.map((img) => (
            <Card key={img.id} className="flex flex-col sm:flex-row gap-4 hover:bg-slate-800/60 transition-colors">
              <div className="w-full sm:w-48 h-32 flex-shrink-0 bg-slate-900/50 rounded-lg overflow-hidden">
                {img.imageUrl ? (
                  <img
                    src={img.imageUrl}
                    alt={img.prompt}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <Image className="w-8 h-8 text-slate-600" />
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-300 truncate">{img.prompt}</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  <span className="px-2 py-0.5 bg-slate-700/30 rounded-full text-xs text-slate-400 capitalize">
                    {styleLabels[img.style] || img.style}
                  </span>
                  <span className="px-2 py-0.5 bg-slate-700/30 rounded-full text-xs text-slate-500">
                    {img.width}x{img.height}
                  </span>
                  <span className="px-2 py-0.5 bg-slate-700/30 rounded-full text-xs text-slate-500">
                    Seed: {img.seed}
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between sm:flex-col sm:justify-end gap-2 sm:justify-start">
                <div className="text-xs text-slate-500 flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {new Date(img.createdAt).toLocaleString()}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => onDownload?.(img.imageUrl || "")} disabled={!img.imageUrl}>
                    <Download className="w-4 h-4" />
                  </Button>
                  {onDelete && (
                    <Button size="sm" variant="ghost" onClick={() => setShowDeleteConfirm(img.id)} className="text-slate-400 hover:text-red-400">
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <Card className="w-full max-w-sm">
            <h3 className="text-lg font-medium text-slate-200 mb-2">
              Delete Generation?
            </h3>
            <p className="text-sm text-slate-400 mb-6">
              This action cannot be undone. The generated image will be
              permanently removed.
            </p>
            <div className="flex gap-3 justify-end">
              <Button
                variant="ghost"
                onClick={() => setShowDeleteConfirm(null)}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => handleDelete(showDeleteConfirm)}
              >
                Delete
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
