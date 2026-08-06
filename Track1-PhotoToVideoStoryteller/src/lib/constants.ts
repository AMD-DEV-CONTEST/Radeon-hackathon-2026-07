export const AI_STYLES = [
  { id: "realistic", name: "Photorealistic", description: "Ultra-realistic photography style", category: "photography", icon: "Camera" },
  { id: "anime", name: "Anime", description: "Japanese animation aesthetic", category: "art", icon: "Sparkles" },
  { id: "digital-art", name: "Digital Art", description: "Modern digital illustration", category: "art", icon: "Palette" },
  { id: "oil-painting", name: "Oil Painting", description: "Classic oil painting texture", category: "traditional", icon: "Brush" },
  { id: "watercolor", name: "Watercolor", description: "Soft watercolor wash effects", category: "traditional", icon: "Droplets" },
  { id: "cyberpunk", name: "Cyberpunk", description: "Neon-lit futuristic cities", category: "theme", icon: "Zap" },
  { id: "fantasy", name: "Fantasy", description: "Magical fantasy landscapes", category: "theme", icon: "Wand" },
  { id: "minimalist", name: "Minimalist", description: "Clean minimal design", category: "design", icon: "Square" },
  { id: "vintage", name: "Vintage", description: "Retro film photography look", category: "photography", icon: "CameraRetro" },
  { id: "abstract", name: "Abstract", description: "Non-representational art", category: "art", icon: "Infinity" },
  { id: "3d-render", name: "3D Render", description: "High-quality 3D visualization", category: "digital", icon: "Cube" },
  { id: "sketch", name: "Sketch", description: "Hand-drawn pencil sketch", category: "traditional", icon: "PenLine" },
];

export const GENERATION_MODES = [
  { id: "text-to-image", name: "Text to Image", description: "Generate images from text descriptions", icon: "Type" },
  { id: "image-edit", name: "Image Edit", description: "Edit and modify existing images", icon: "Edit3" },
  { id: "style-transfer", name: "Style Transfer", description: "Apply artistic styles to images", icon: "Layers" },
  { id: "enhance", name: "Enhance", description: "Upscale and enhance image quality", icon: "Maximize" },
  { id: "variation", name: "Variation", description: "Create variations of an image", icon: "RefreshCw" },
];

export const PRESET_PROMPTS = [
  "A serene Japanese garden in autumn with maple leaves falling, soft golden hour lighting, photorealistic",
  "A futuristic cyberpunk city with neon lights reflecting on wet streets, flying vehicles, ultra detailed",
  "Portrait of a wise old wizard in a mystical forest, fantasy art style, magical glowing elements",
  "A cozy coffee shop interior with warm lighting, bookshelves, rain on windows, cinematic photography",
  "Abstract geometric patterns in vibrant colors, modern digital art, smooth gradients and clean lines",
  "A majestic dragon flying over medieval castle, epic fantasy scene, dramatic lighting, highly detailed",
  "Underwater coral reef ecosystem with colorful fish, tropical marine life, national geographic style",
  "Minimalist architectura linterior with natural light, clean lines, Scandi design, modern aesthetic",
];

export function generateSeed(): number {
  return Math.floor(Math.random() * 2147483647);
}

export function getRandomPrompt(): string {
  return PRESET_PROMPTS[Math.floor(Math.random() * PRESET_PROMPTS.length)];
}
