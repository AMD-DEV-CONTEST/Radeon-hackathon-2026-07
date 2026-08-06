var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// server.ts
var import_express = __toESM(require("express"), 1);
var import_path = __toESM(require("path"), 1);
var import_dotenv = __toESM(require("dotenv"), 1);
var import_genai = require("@google/genai");
var import_vite = require("vite");
import_dotenv.default.config();
var app = (0, import_express.default)();
var PORT = 3e3;
app.use(import_express.default.json());
var aiClient = null;
function getAiClient() {
  if (!aiClient) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      console.warn("GEMINI_API_KEY environment variable is not defined. AI Chatbot queries will fail.");
    }
    aiClient = new import_genai.GoogleGenAI({ apiKey: apiKey || "" });
  }
  return aiClient;
}
var SYSTEM_INSTRUCTION = `You are HealthSphere AI, a professional, intelligent, and highly composed Public Health Assistant.
Your primary objective is to help communities make informed, evidence-based health decisions by providing educational information on diseases, hygiene, vaccination, nutrition, and general wellness.

CRITICAL RULES:
1. ANSWER ONLY public health, medical, wellness, and disease-related questions.
2. If the user asks about unrelated topics (such as politics, sports, general coding, celebrities, etc.), politely decline by saying: "I am designed to assist with public health-related inquiries only. Please let me know if you have a health-related question."
3. Include a professional medical disclaimer at the end of your response when appropriate: "Disclaimer: I am an AI public health assistant, not a doctor. This information is for educational purposes and does not substitute for professional medical advice, diagnosis, or treatment."
4. Maintain a reassuring, clean, objective, and professional tone. Do not use excessive emojis, and keep the layout extremely clean and well-structured with bullet points where necessary.`;
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
    const formattedContents = messages.map((msg) => ({
      role: msg.role === "assistant" ? "model" : "user",
      parts: [{ text: msg.content }]
    }));
    const response = await ai.models.generateContent({
      model: "gemini-2.5-flash",
      contents: formattedContents,
      config: {
        systemInstruction: SYSTEM_INSTRUCTION
      }
    });
    const replyText = response.text || "I was unable to generate a response. Please try again.";
    return res.json({ reply: replyText });
  } catch (error) {
    console.error("Error calling Gemini API:", error);
    return res.status(500).json({
      error: "An error occurred while communicating with the AI. " + (error.message || "")
    });
  }
});
async function initServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await (0, import_vite.createServer)({
      server: { middlewareMode: true },
      appType: "spa"
    });
    app.use(vite.middlewares);
  } else {
    const distPath = import_path.default.join(process.cwd(), "dist");
    app.use(import_express.default.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(import_path.default.join(distPath, "index.html"));
    });
  }
  app.listen(PORT, "0.0.0.0", () => {
    console.log(`[HealthSphere AI] Server running on http://0.0.0.0:${PORT}`);
  });
}
initServer().catch((err) => {
  console.error("Failed to start server:", err);
});
//# sourceMappingURL=server.cjs.map
