import express from "express";
import path from "path";
import dotenv from "dotenv";
import { GoogleGenAI } from "@google/genai";
import { createServer as createViteServer } from "vite";

dotenv.config();

const app = express();
const PORT = 3000;

app.use(express.json());

// Initialize Gemini client lazily
let aiClient: GoogleGenAI | null = null;
function getAiClient() {
  if (!aiClient) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      console.warn("GEMINI_API_KEY environment variable is not defined. AI Chatbot queries will fail.");
    }
    aiClient = new GoogleGenAI({ apiKey: apiKey || "" });
  }
  return aiClient;
}

const SYSTEM_INSTRUCTION = `You are HealthSphere AI, a professional, intelligent, and highly composed Public Health Assistant.
Your primary objective is to help communities make informed, evidence-based health decisions by providing educational information on diseases, hygiene, vaccination, nutrition, and general wellness.

CRITICAL RULES:
1. ANSWER ONLY public health, medical, wellness, and disease-related questions.
2. If the user asks about unrelated topics (such as politics, sports, general coding, celebrities, etc.), politely decline by saying: "I am designed to assist with public health-related inquiries only. Please let me know if you have a health-related question."
3. Include a professional medical disclaimer at the end of your response when appropriate: "Disclaimer: I am an AI public health assistant, not a doctor. This information is for educational purposes and does not substitute for professional medical advice, diagnosis, or treatment."
4. Maintain a reassuring, clean, objective, and professional tone. Do not use excessive emojis, and keep the layout extremely clean and well-structured with bullet points where necessary.`;

// API routes FIRST
app.post("/api/chat", async (req, res) => {
  try {
    const { messages } = req.body;
    if (!messages || !Array.isArray(messages)) {
      return res.status(400).json({ error: "Invalid request. 'messages' must be an array." });
    }

    const ai = getAiClient();
    if (!process.env.GEMINI_API_KEY) {
      return res.status(500).json({ 
        error: "Gemini API key is not configured on the server. Please add GEMINI_API_KEY to your Secrets." 
      });
    }

    // Map client messages to Gemini content format: { role: 'user' | 'model', parts: [{ text: string }] }
    const formattedContents = messages.map((msg: any) => ({
      role: msg.role === "assistant" ? "model" : "user",
      parts: [{ text: msg.content }]
    }));

    const response = await ai.models.generateContent({
      model: "gemini-2.5-flash",
      contents: formattedContents,
      config: {
        systemInstruction: SYSTEM_INSTRUCTION,
      }
    });

    const replyText = response.text || "I was unable to generate a response. Please try again.";
    return res.json({ reply: replyText });
  } catch (error: any) {
    console.error("Error calling Gemini API:", error);
    return res.status(500).json({ 
      error: "An error occurred while communicating with the AI. " + (error.message || "") 
    });
  }
});

// Serve Vite dev server or built client
async function initServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`[HealthSphere AI] Server running on http://0.0.0.0:${PORT}`);
  });
}

initServer().catch((err) => {
  console.error("Failed to start server:", err);
});
