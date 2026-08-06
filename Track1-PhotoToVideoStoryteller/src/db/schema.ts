import { pgTable, serial, text, timestamp, boolean, integer } from "drizzle-orm/pg-core";

export const generations = pgTable("generations", {
  id: serial("id").primaryKey(),
  prompt: text("prompt").notNull(),
  negativePrompt: text("negative_prompt"),
  style: text("style").notNull().default("realistic"),
  mode: text("mode").notNull().default("text-to-image"),
  imageUrl: text("image_url"),
  thumbnailUrl: text("thumbnail_url"),
  width: integer("width").default(1024),
  height: integer("height").default(1024),
  seed: integer("seed"),
  steps: integer("steps").default(30),
  guidanceScale: integer("guidance_scale").default(7),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
  isPublic: boolean("is_public").default(true),
  userId: text("user_id"),
});

export const styles = pgTable("styles", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  description: text("description"),
  previewUrl: text("preview_url"),
  category: text("category").notNull(),
  isPremium: boolean("is_premium").default(false),
});

export const userPreferences = pgTable("user_preferences", {
  id: serial("id").primaryKey(),
  userId: text("user_id").notNull().unique(),
  defaultWidth: integer("default_width").default(1024),
  defaultHeight: integer("default_height").default(1024),
  defaultSteps: integer("default_steps").default(30),
  defaultStyle: text("default_style").default("realistic"),
  autoEnhance: boolean("auto_enhance").default(false),
});
