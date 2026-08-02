from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from dotenv import load_dotenv
import os
from tavily import TavilyClient
from groq import Groq
import time
load_dotenv()

app = FastAPI()
PROVIDER = os.getenv("PROVIDER", "groq")

if PROVIDER == "groq":
    client = OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )
    MODEL_NAME = "llama-3.1-8b-instant"
else:
    client = OpenAI(
        api_key=os.getenv("RADEON_API_KEY"),
        base_url=os.getenv("RADEON_BASE_URL"),
    )
    MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct-AWQ"

print(f"LLM provider: {PROVIDER} | model: {MODEL_NAME}")

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
tavily = TavilyClient(api_key=TAVILY_KEY)

TRUSTED_DOMAINS = [
    "who.int", "nih.gov", "cdc.gov", "mayoclinic.org",
    "medlineplus.gov", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov"
]


class ChatRequest(BaseModel):
    message: str
    history: list


def retrieve_web(query):
    try:
        result = tavily.search(
            query=query,
            search_depth="basic",
            max_results=4,
            include_domains=TRUSTED_DOMAINS,
        )
        print(f"[WEB SEARCH] Got {len(result.get('results', []))} results")
        return result
    except Exception as e:
        print("Tavily search failed:", e)
        return {"results": []}


import json
import re


def needs_web_search(message, local_context):
    router_prompt = f"""You are a routing agent for a medical assistant.
User question: "{message}"

Local knowledge base excerpt (may or may not be relevant):
{local_context if local_context else "(no local match found)"}

Decide if the local excerpt is sufficient to answer the question, or if you
need to search trusted medical websites for more specific or current info.

Respond with ONLY valid JSON, no other text:
{{"need_web_search": true or false, "search_query": "short search query if needed, else empty string"}}
"""
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": router_prompt}],
            temperature=0,
        )
        raw = res.choices[0].message.content.strip()
        raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        decision = json.loads(raw)

        need_web = decision["need_web_search"]
        search_query = decision["search_query"]

        # Safety net: if the model says "search" but gives no query, fall back
        # to the original user message so Tavily always gets something usable.
        if need_web and not search_query.strip():
            search_query = message
        print(f"[ROUTER DECISION] need_web={need_web}, query='{search_query}'")
        return need_web, search_query
    except Exception as e:
        print("Router decision failed, skipping web search:", e)
        return False, ""
    


def load_rag():
    docs = []

    for file in os.listdir("medical_data"):
        if file.endswith(".txt"):
            loader = TextLoader(f"medical_data/{file}", encoding="utf-8")
            docs.extend(loader.load())

    splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    split_docs = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    return FAISS.from_documents(split_docs, embeddings)


db = None


@app.on_event("startup")
def startup_event():
    global db
    try:
        print("Loading RAG...")
        db = load_rag()
        print("RAG Loaded ✅")
    except Exception as e:
        print("RAG ERROR:", e)


@app.get("/")
def root():
    return {"message": "Backend is working", "provider": PROVIDER, "model": MODEL_NAME}


def clean_text(text):
    import re
    text = re.sub(r'([.,!?])([A-Za-z])', r'\1 \2', text)
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


@app.post("/chat")
def chat(req: ChatRequest):
    start_time = time.time()

    docs = db.similarity_search(req.message, k=3)
    local_context = "\n".join([d.page_content for d in docs])

    use_web, search_query = needs_web_search(req.message, local_context)

    web_context = ""
    if use_web:
        web_result = retrieve_web(search_query)
        web_parts = []
        for r in web_result.get("results", []):
            web_parts.append(f"[{r.get('url')}]\n{r.get('content')}")
        web_context = "\n\n".join(web_parts)

    combined_context = local_context
    if web_context:
        combined_context += "\n\n--- Additional trusted web sources ---\n\n" + web_context

    system_prompt = f"""
    You are MedAgent, an advanced AI medical assistant. 
    Your goal is to help users identify possible medical conditions based on their symptoms.
    use this context:
    {combined_context}
    PROTOCOL:
    1.  **Analyze Symptoms**: When the user provides symptoms, analyze them.
    2.  **Ask Clarifying Questions**:
        - Ask 1–2 questions at a time ONLY.
        - NEVER say things like: "you repeated", "you already said", "let me rephrase"
        - ALWAYS accept the user's answer as valid input, even if short or unclear.
        - If unclear, simply ask the next logical question.
    3.  **Detect Emergencies**: If symptoms indicate a life-threatening emergency
        (e.g., heart attack, stroke, anaphylaxis), STOP questioning and warn the
        user immediately to seek emergency care.
    4.  **Tone**: Be professional, empathetic, and objective.

    When you are ready to provide a diagnosis (usually after 2-3 turns or if the
    user asks), simply state "I have enough information to generate your report."
    """

    messages = [{"role": "system", "content": system_prompt}] + req.history + [
        {"role": "user", "content": req.message}
    ]

    res = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages
    )

    reply = res.choices[0].message.content
    reply = clean_text(reply)

    elapsed = round(time.time() - start_time, 2)
    print(f"[TIMING] Total /chat response time: {elapsed}s (web_search={use_web})")

    return {"reply": reply, "used_web_search": use_web, "response_time_seconds": elapsed}


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportRequest(BaseModel):
    history: list


@app.post("/report")
def generate_report(req: ReportRequest):

    full_conversation = "\n".join([msg["content"] for msg in req.history])

    prompt = f"""
    Based on the following conversation, generate a medical report:

    {full_conversation}

    Include:
    - Possible condition
    - Reasoning
    - Precautions
    - Recommended doctor
    """

    res = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}]
    )

    return {"report": res.choices[0].message.content}
