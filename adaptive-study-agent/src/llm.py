from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama

# -----------------------------
# Project paths
# -----------------------------
project_root = Path(__file__).resolve().parent.parent
db_path = project_root / "chroma_db"

# -----------------------------
# Load embedding model
# -----------------------------
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# -----------------------------
# Load Chroma database
# -----------------------------
vectorstore = Chroma(
    persist_directory=str(db_path),
    embedding_function=embeddings
)

# -----------------------------
# Create retriever
# -----------------------------
retriever = vectorstore.as_retriever(
    search_kwargs={"k": 6}
)

# -----------------------------
# Connect to Ollama
# Replace model name if needed
# -----------------------------
llm = ChatOllama(
    model="qwen2.5:3b"
)

# -----------------------------
# Ask question
# -----------------------------
question = input("Enter your question: ")

# -----------------------------
# Retrieve relevant chunks
# -----------------------------
docs = retriever.invoke(question)

# Combine chunks into one context
context = "\n\n".join(doc.page_content for doc in docs)

# -----------------------------
# Prompt
# -----------------------------
prompt = f"""
You are an intelligent AI Study Assistant.

Answer the user's question ONLY using the context below.

If the answer is not found in the context, say:

"I couldn't find that information in the uploaded document."

Context:
{context}

Question:
{question}

Answer:
"""

# -----------------------------
# Generate answer
# -----------------------------
response = llm.invoke(prompt)

print("\n==============================")
print("AI ANSWER")
print("==============================\n")

print(response.content)