# 📚 Adaptive Study Agent

An AI-powered RAG (Retrieval-Augmented Generation) study assistant built for the **AMD AI DevMaster Hackathon 2026**.

The application enables students to upload one or more PDF documents and interact with them using a locally running Large Language Model (LLM). It retrieves relevant content from the uploaded study material and generates accurate, context-aware responses without relying on cloud APIs.

---

# 🚀 Features

### 📄 Multi-PDF Upload
- Upload one or more PDF documents.
- Supports lecture notes, textbooks, and study materials.

### 🔍 Intelligent Question Answering
- Ask natural language questions.
- Retrieves the most relevant document chunks using RAG.
- Answers strictly from the uploaded documents.

### 📝 AI Quiz Generator
Generate customizable MCQs.

Options:
- Easy
- Medium
- Hard

Custom number of questions (default: 10)

---

### 📚 Flashcard Generator

Automatically creates revision flashcards from uploaded notes.

Example:

Q: What is Encapsulation?

A: Encapsulation is the process of wrapping data and methods together into a single unit.

---

### 📅 Study Planner

Creates a personalized study schedule based on the uploaded material.

Users can choose:

- Number of study days
- Balanced topic distribution

---

### 📄 Document Summarization

Generates concise bullet-point summaries including:

- Main Topics
- Important Concepts
- Definitions
- Key Points
- Revision Notes

---

### 🎯 Exam Tips

Highlights:

- Frequently tested concepts
- Important topics
- Revision strategy

---

### 📖 Important Definitions

Extracts key definitions from the uploaded study material.

---

### ➗ Formula Extraction

Automatically extracts important formulas and mathematical expressions.

---

### 🧒 Explain Like I'm 10

Simplifies difficult concepts into beginner-friendly explanations.

---

# 🧠 Technology Stack

## Frontend

- Streamlit

## LLM

- Ollama
- Qwen2.5:3B

## Embeddings

- sentence-transformers/all-MiniLM-L6-v2

## Vector Database

- ChromaDB

## Framework

- LangChain

---

# 🏗️ Architecture

```
                Upload PDFs
                      │
                      ▼
              PDF Loader (PyPDF)
                      │
                      ▼
         Recursive Text Splitter
                      │
                      ▼
      HuggingFace Embeddings
                      │
                      ▼
             Chroma Vector DB
                      │
                      ▼
         Similarity Retrieval (RAG)
                      │
                      ▼
             Ollama (Qwen2.5)
                      │
                      ▼
        Context-Aware AI Responses
```

---

# ⚙️ Project Workflow

1. Upload one or more PDFs.
2. Extract document text.
3. Split into overlapping chunks.
4. Generate embeddings.
5. Store embeddings in ChromaDB.
6. Retrieve relevant chunks for each query.
7. Send retrieved context to the local LLM.
8. Generate accurate responses.

---

# 📂 Project Structure

```
adaptive-study-agent/

│
├── app.py
├── requirements.txt
├── README.md
│
├── data/
│   └── Sample PDFs
│
├── src/
│   ├── loader.py
│   ├── splitter.py
│   ├── embeddings.py
│   ├── vectorstore.py
│   └── rag.py
│
└── chroma_db/
```

---

# 💻 Installation

## Clone Repository

```bash
git clone <repository-url>

cd adaptive-study-agent
```

---

## Create Virtual Environment

```bash
python -m venv venv
```

Windows

```bash
venv\Scripts\activate
```

Linux/macOS

```bash
source venv/bin/activate
```

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Install Ollama

Download from:

https://ollama.com

---

## Pull Model

```bash
ollama pull qwen2.5:3b
```

---

## Start Ollama

```bash
ollama serve
```

---

## Launch Application

```bash
streamlit run app.py
```

---

# 📦 Requirements

Main libraries used:

- Streamlit
- LangChain
- ChromaDB
- HuggingFace Embeddings
- Ollama
- PyPDF
- Sentence Transformers

See `requirements.txt` for the complete dependency list.

---

# 🎯 Future Improvements

- Chat history and conversational memory
- Persistent vector database
- Support for DOCX, PPTX and TXT
- AI-generated notes
- PDF highlighting with source references
- Voice interaction
- Export summaries and quizzes as PDF
- GPU acceleration and benchmarking on supported AMD Radeon hardware

---

# 🏆 Hackathon Highlights

✅ Fully local AI application

✅ Retrieval-Augmented Generation (RAG)

✅ Multi-document support

✅ Multiple AI learning tools

✅ Context-aware responses

✅ No external API required

---

# 📸 Demo

The demonstration includes:

- Uploading study material
- Processing PDFs
- Asking questions
- AI-generated answers
- Quiz generation
- Flashcard generation
- Study plan creation
- Document summarization

---

# 👩‍💻 Author

**Rakshita M**

Vellore Institute of Technology (VIT)

Built for the **AMD AI DevMaster Hackathon 2026**.