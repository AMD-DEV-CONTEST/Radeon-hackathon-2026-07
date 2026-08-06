# IndusMind AI - Final Presentation Script
**Duration:** ~5 Minutes
**Team Size:** 4 People

---

## Speaker 1: Introduction & Problem Statement (1 min 15 sec)
**[Slide 1: Title Slide - IndusMind AI]**
"Hello everyone, we are the team behind **IndusMind AI**. Our project is an Industrial Asset Intelligence & RCA Copilot. In heavy industries like manufacturing and oil & gas, when a machine fails, engineers waste hours digging through fragmented maintenance logs, 500-page OEM manuals, and sensor data trying to figure out what went wrong. We built IndusMind AI to solve this exact problem."

**[Slide 2: The Solution & Tech Stack]**
"IndusMind is an AI-powered knowledge layer. You can ask it natural language questions like 'Why did Pump P-101 fail?' and it instantly gives you an answer with exact citations pointing to the specific page in the manual or maintenance record. 
To build this, we used a robust tech stack: React for the frontend, Spring Boot for a secure backend, and a local Python FastAPI service running a custom fine-tuned LLaMA-3 AI model."

---

## Speaker 2: The Frontend Experience (1 min 15 sec)
**[Slide 3: Frontend Architecture & UI]**
"I'd like to walk you through the user experience we built. Our frontend is a modern single-page application built with React 19, TypeScript, and Vite. We prioritized a fast, responsive, and intuitive interface."

**[Slide 4: Live Demo / Screenshots of Dashboard]**
"When an engineer logs in securely via JWT authentication, they are greeted by the Command Center. From here, they can navigate to the 'AI Copilot' to ask questions, or the 'Asset 360' view to see a complete timeline of failures and maintenance actions. We didn't want a generic chatbot; we designed a specialized industrial interface where every AI answer clearly displays its source evidence, building trust with the engineer."

---

## Speaker 3: The AI Brain (1 min 15 sec)
**[Slide 5: RAG Pipeline & Vector Database]**
"For the AI, privacy and accuracy are critical. We couldn't just send confidential industrial data to ChatGPT. Instead, we built a fully local Retrieval-Augmented Generation (RAG) pipeline using Python and FastAPI. When documents are uploaded, we extract the text and store it in an embedded ChromaDB vector database."

**[Slide 6: Fine-Tuned LLaMA-3 LoRA]**
"But the most exciting part is our generation layer. Instead of relying on cloud APIs, we fine-tuned our own LLaMA-3 model using LoRA adapters specifically for industrial engineering terminology. It runs completely offline on a local GPU using 4-bit quantization, giving us extremely fast, highly accurate, and secure answers without any data ever leaving the local network."

---

## Speaker 4: The Backend & Conclusion (1 min 15 sec)
**[Slide 7: Spring Boot & Security]**
"Tying everything together is our core backend, built on Java 21 and Spring Boot. While the AI handles the natural language processing, the Spring Boot layer is responsible for strict security, Role-Based Access Control, and managing the PostgreSQL database. It acts as the secure gateway, ensuring that an engineer can only query data they are authorized to see."

**[Slide 8: Conclusion]**
"In conclusion, IndusMind AI takes scattered, unstructured industrial data and turns it into immediate, actionable intelligence. It operates fully on-premise, ensuring data privacy, and it proves that with fine-tuned local models like LLaMA-3, we can build highly specialized, production-ready AI tools for heavy industry. 
Thank you, and we'd be happy to answer any questions."
