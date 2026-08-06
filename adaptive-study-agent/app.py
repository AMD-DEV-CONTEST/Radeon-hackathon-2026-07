"""
Adaptive Study Agent
A RAG-based learning assistant built for the AMD AI DevMaster Hackathon.

Stack: Streamlit, LangChain, ChromaDB, HuggingFace Embeddings, Ollama (Qwen2.5:3b)
"""

# =========================================================
# IMPORTS
# =========================================================
import os
import hashlib
import tempfile

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama


# =========================================================
# CONSTANTS
# =========================================================
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "qwen2.5:3b"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

STUDY_SYSTEM_PROMPT = "You are an AI Study Assistant."

# Every generation feature now runs RAG instead of stuffing the whole PDF
# into the prompt: we retrieve only the chunks relevant to a task-specific
# query and send just those. Each task gets its own retrieval query and k
# (number of chunks), since some tasks (e.g. a study plan spanning the
# whole document) benefit from broader coverage than others (e.g. a single
# QA question).
RETRIEVAL_CONFIG = {
    "qa": {"k": 6},
    "summary": {"query": "Generate a complete summary covering all main topics, concepts, and key points", "k": 10},
    "quiz": {"query": "Key concepts, facts, and topics suitable for quiz questions", "k": 8},
    "flashcards": {"query": "Key terms, concepts, and facts for revision flashcards", "k": 8},
    "study_plan": {"query": "Main topics and concepts across the document for study planning", "k": 10},
    "eli10": {"query": "Core concepts of the document explained simply", "k": 8},
    "exam_tips": {"query": "Important topics likely to be tested in an exam", "k": 8},
    "definitions": {"query": "Important terms and their definitions", "k": 10},
    "formulas": {"query": "Formulas, equations, and mathematical relationships", "k": 10},
}


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Adaptive Study Agent",
    page_icon="📚",
    layout="wide",
)


# =========================================================
# SESSION STATE INITIALIZATION
# =========================================================
def init_session_state():
    """Ensure all required session state keys exist."""
    defaults = {
        "vectorstore": None,
        "retriever": None,     # default retriever (QA), created once per vectorstore
        "retrievers": {},      # cache of retrievers keyed by k, created once each
        "processed_files": None,
        "processed_hash": None,
        "chat_history": [],
        "last_answer": None,
        "last_sources": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# =========================================================
# CACHED RESOURCES (created once, reused across reruns)
# =========================================================
@st.cache_resource(show_spinner=False)
def get_embeddings():
    """Load and cache the HuggingFace embedding model."""
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


@st.cache_resource(show_spinner=False)
def get_llm():
    """Instantiate and cache the Ollama LLM client.

    keep_alive keeps the model resident in Ollama's memory between calls so
    it doesn't get reloaded from disk on every request. num_predict is
    capped at 512 (down from 1024) since RAG-scoped prompts need shorter,
    more focused completions. num_ctx is trimmed to fit the now much
    smaller RAG context instead of a full document, and num_thread lets
    Ollama use all available CPU cores for faster local inference.
    """
    return ChatOllama(
        model=LLM_MODEL,
        temperature=0.3,
        keep_alive="30m",
        num_predict=512,
        num_ctx=4096,
        num_thread=os.cpu_count(),
    )


# =========================================================
# ERROR HANDLING HELPERS
# =========================================================
def safe_llm_call(prompt: str):
    """Call the LLM once, with unified error handling. Returns text or None."""
    try:
        llm = get_llm()
        response = llm.invoke(prompt)
        return response.content
    except Exception as exc:
        st.error(
            "⚠️ Could not get a response from Ollama. Make sure Ollama is "
            f"running and the '{LLM_MODEL}' model is pulled.\n\nDetails: {exc}"
        )
        return None


# =========================================================
# PDF PROCESSING
# =========================================================
def save_uploaded_files(uploaded_files) -> list:
    """Save uploaded PDFs to a temporary directory and return their paths."""
    temp_dir = tempfile.mkdtemp(prefix="study_agent_pdfs_")
    saved_paths = []
    for uploaded_file in uploaded_files:
        file_path = os.path.join(temp_dir, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        saved_paths.append(file_path)
    return saved_paths


def load_all_pdfs(file_paths: list) -> list:
    """Load every PDF and combine all pages into a single list of Documents."""
    all_docs = []
    for path in file_paths:
        try:
            loader = PyPDFLoader(path)
            docs = loader.load()
            all_docs.extend(docs)
        except Exception as exc:
            st.error(f"⚠️ Failed to load PDF '{os.path.basename(path)}'.\n\nDetails: {exc}")
    return all_docs


def split_documents(documents: list) -> list:
    """Split combined documents into overlapping chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(documents)


def build_vectorstore(chunks: list):
    """Embed chunks and store them in an in-memory Chroma vector database.

    No persist_directory is used: the vectorstore only needs to live for the
    current session, and skipping disk writes avoids unnecessary I/O
    overhead when processing PDFs.
    """
    embeddings = get_embeddings()
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
    )
    return vectorstore


def hash_uploaded_files(uploaded_files) -> str:
    """Compute a stable hash of the uploaded files' contents.

    Used to detect when the user clicks "Process PDFs" again on the exact
    same files so we can skip re-embedding entirely instead of redoing all
    the work.
    """
    hasher = hashlib.sha256()
    for f in uploaded_files:
        hasher.update(f.name.encode("utf-8"))
        hasher.update(f.getbuffer())
    return hasher.hexdigest()


def process_pdfs(uploaded_files):
    """Full pipeline: save -> load -> split -> embed -> store -> build retriever.

    Skips all work if these exact files were already processed. The
    retriever is built ONCE here, right after the vector store is created,
    and cached in st.session_state so no feature ever recreates it.
    """
    files_hash = hash_uploaded_files(uploaded_files)
    if st.session_state.get("processed_hash") == files_hash and st.session_state.vectorstore is not None:
        st.info("ℹ️ These PDFs are already processed — skipping re-embedding.")
        return

    with st.spinner("💾 Saving uploaded PDFs..."):
        file_paths = save_uploaded_files(uploaded_files)

    with st.spinner("📖 Loading PDF content..."):
        raw_docs = load_all_pdfs(file_paths)

    if not raw_docs:
        st.error("⚠️ No readable content was found in the uploaded PDF(s).")
        return

    with st.spinner("✂️ Splitting document into chunks..."):
        chunks = split_documents(raw_docs)

    if not chunks:
        st.error("⚠️ Document splitting produced no chunks. Please check the PDF content.")
        return

    with st.spinner("🧠 Generating embeddings and building vector database..."):
        vectorstore = build_vectorstore(chunks)

    # Reset per-k retriever cache for the new vectorstore, then eagerly
    # create the default (QA) retriever once so it's ready immediately.
    st.session_state.vectorstore = vectorstore
    st.session_state.retrievers = {}
    st.session_state.retriever = get_retriever(RETRIEVAL_CONFIG["qa"]["k"])
    st.session_state.processed_files = [f.name for f in uploaded_files]
    st.session_state.processed_hash = files_hash

    st.success(f"✅ Processed {len(uploaded_files)} PDF(s) into {len(chunks)} chunks!")


# =========================================================
# RETRIEVAL (retriever created once per k, reused everywhere)
# =========================================================
def get_retriever(k: int):
    """Return the cached retriever for a given k, creating it only once.

    The vectorstore is embedded once; on top of it we lazily build one
    retriever per distinct k value the app needs and cache each in
    st.session_state.retrievers, so no retriever is ever rebuilt on rerun.
    """
    retrievers = st.session_state.retrievers
    if k not in retrievers:
        retrievers[k] = st.session_state.vectorstore.as_retriever(search_kwargs={"k": k})
    return retrievers[k]


def build_context(chunks: list) -> str:
    """Combine retrieved chunks into a single context string."""
    return "\n\n---\n\n".join(doc.page_content for doc in chunks)


def retrieve_for_task(task: str, query: str = None):
    """Retrieve chunks for a named task using its configured retriever/k.

    Every feature funnels through here and through retriever.invoke(...),
    so retrieval logic lives in exactly one place.
    """
    config = RETRIEVAL_CONFIG[task]
    retriever = get_retriever(config["k"])
    return retriever.invoke(query if query is not None else config["query"])


# =========================================================
# QUESTION ANSWERING
# =========================================================
def build_qa_prompt(question: str, context: str) -> str:
    """Construct the strict context-only QA prompt."""
    return f"""{STUDY_SYSTEM_PROMPT}
Answer ONLY using the context below. If it's not there, reply exactly:
"I couldn't find that information in the uploaded PDF."
Use bullet points where helpful.

Context:
{context}

Question: {question}
Answer:"""


def answer_question(question: str):
    """Full QA pipeline: retrieve -> build context -> prompt -> generate."""
    chunks = retrieve_for_task("qa", query=question)

    if not chunks:
        st.warning("⚠️ No relevant content was found for this question.")
        return None, []

    context = build_context(chunks)
    prompt = build_qa_prompt(question, context)
    answer = safe_llm_call(prompt)
    return answer, chunks


# =========================================================
# GENERATION HELPERS (Summary, Quiz, Flashcards, Study Plan, Bonus)
# All of these retrieve task-relevant chunks first, then generate from
# that small context instead of the full document.
# =========================================================
def generate_summary():
    context = build_context(retrieve_for_task("summary"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, write a study summary with these sections:
• Main Topics
• Important Concepts
• Definitions
• Key Points
• Revision Notes

Context:
{context}

Summary:"""
    return safe_llm_call(prompt)


def generate_quiz(difficulty: str, num_questions: int):
    context = build_context(retrieve_for_task("quiz"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, write exactly {num_questions} multiple-choice questions at {difficulty} difficulty.
Cover different topics, avoid repeats. Format each exactly as:

Q<number>. <question>
A. <option>
B. <option>
C. <option>
D. <option>
Correct Answer: <letter>

Context:
{context}

Quiz:"""
    return safe_llm_call(prompt)


def generate_flashcards(num_cards: int):
    context = build_context(retrieve_for_task("flashcards"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, write exactly {num_cards} flashcards. Format each exactly as:

Flashcard <number>
Q: <question>
A: <answer>

Context:
{context}

Flashcards:"""
    return safe_llm_call(prompt)


def generate_study_plan(days: int):
    context = build_context(retrieve_for_task("study_plan"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, build a day-wise study plan spread evenly across {days} days.
For each day include: Topics to study, Revision tasks, Practice tasks.

Context:
{context}

Study Plan:"""
    return safe_llm_call(prompt)


def generate_eli10():
    context = build_context(retrieve_for_task("eli10"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, explain the key ideas as if to a 10-year-old: simple language, short sentences, relatable examples.

Context:
{context}

Explanation:"""
    return safe_llm_call(prompt)


def generate_exam_tips():
    context = build_context(retrieve_for_task("exam_tips"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, give practical exam-prep tips as bullet points. Focus on what's most likely tested.

Context:
{context}

Exam Tips:"""
    return safe_llm_call(prompt)


def generate_definitions():
    context = build_context(retrieve_for_task("definitions"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, extract important definitions. Format as:
• <Term>: <Definition>

Context:
{context}

Important Definitions:"""
    return safe_llm_call(prompt)


def generate_formulas():
    context = build_context(retrieve_for_task("formulas"))
    prompt = f"""{STUDY_SYSTEM_PROMPT}
Using ONLY the context below, extract important formulas with a short explanation each. If none exist, say so. Format as:
• <Formula>: <Short Explanation>

Context:
{context}

Important Formulas:"""
    return safe_llm_call(prompt)


# =========================================================
# SIDEBAR
# =========================================================
def render_sidebar():
    with st.sidebar:
        st.header("ℹ️ About")
        st.markdown(
            """
**Adaptive Study Agent**

* 🔎 RAG-based Learning Assistant
* 🗂️ Chroma Vector Database
* 🤗 HuggingFace Embeddings
* 🦙 Ollama Local LLM
* 🏆 Built for AMD AI DevMaster Hackathon
            """
        )
        st.divider()
        if st.session_state.processed_files:
            st.subheader("📁 Loaded Documents")
            for name in st.session_state.processed_files:
                st.caption(f"• {name}")


# =========================================================
# UI SECTIONS
# =========================================================
def render_upload_section():
    st.subheader("📤 Upload Study Material")
    uploaded_files = st.file_uploader(
        "Upload one or more PDF files",
        type=["pdf"],
        accept_multiple_files=True,
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        process_clicked = st.button("⚙️ Process PDFs", use_container_width=True)

    if process_clicked:
        if not uploaded_files:
            st.error("⚠️ Please upload at least one PDF before processing.")
        else:
            process_pdfs(uploaded_files)


def render_qa_section():
    st.subheader("💬 Ask a Question")
    question = st.text_input("Enter your question about the uploaded document(s):")
    ask_clicked = st.button("🔍 Get Answer")

    if ask_clicked:
        if st.session_state.retriever is None:
            st.error("⚠️ Please upload and process a PDF first.")
        elif not question or not question.strip():
            st.error("⚠️ Please enter a question.")
        else:
            with st.spinner("🤔 Thinking..."):
                answer, chunks = answer_question(question)
            if answer:
                st.session_state.last_answer = answer
                st.session_state.last_sources = chunks

    if st.session_state.last_answer:
        st.markdown("### ✅ Answer")
        st.markdown(st.session_state.last_answer)

        if st.session_state.last_sources:
            with st.expander("📑 View Retrieved Chunks"):
                for i, doc in enumerate(st.session_state.last_sources, start=1):
                    page = doc.metadata.get("page", "N/A")
                    source = doc.metadata.get("source", "unknown")
                    st.markdown(f"**Chunk {i} — Page {page} — {os.path.basename(str(source))}**")
                    st.text(doc.page_content)
                    st.markdown("---")


def render_summary_section():
    st.subheader("📄 Document Summary")
    if st.button("📄 Generate Summary"):
        if st.session_state.retriever is None:
            st.error("⚠️ Please upload and process a PDF first.")
        else:
            with st.spinner("🧠 Retrieving relevant content and generating summary..."):
                summary = generate_summary()
            if summary:
                st.markdown(summary)


def render_quiz_section():
    st.subheader("📝 Quiz Generator")

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"], index=1)
    with col2:
        num_questions = st.number_input(
            "Number of MCQs", min_value=1, max_value=50, value=10, step=1
        )

    if st.button("📝 Generate Quiz"):
        if st.session_state.retriever is None:
            st.error("⚠️ Please upload and process a PDF first.")
        else:
            with st.spinner(f"🧠 Generating {num_questions} {difficulty.lower()} MCQs..."):
                quiz = generate_quiz(difficulty, int(num_questions))
            if quiz:
                with st.expander("📝 View Generated Quiz", expanded=True):
                    st.markdown(quiz)


def render_flashcard_section():
    st.subheader("📚 Flashcards")
    num_cards = st.number_input(
        "Number of Flashcards", min_value=1, max_value=50, value=10, step=1
    )

    if st.button("📚 Generate Flashcards"):
        if st.session_state.retriever is None:
            st.error("⚠️ Please upload and process a PDF first.")
        else:
            with st.spinner(f"🧠 Generating {num_cards} flashcards..."):
                flashcards = generate_flashcards(int(num_cards))
            if flashcards:
                with st.expander("📚 View Flashcards", expanded=True):
                    st.markdown(flashcards)


def render_study_plan_section():
    st.subheader("📅 Study Planner")
    days = st.slider("Days until exam", min_value=1, max_value=30, value=7)

    if st.button("📅 Generate Study Plan"):
        if st.session_state.retriever is None:
            st.error("⚠️ Please upload and process a PDF first.")
        else:
            with st.spinner(f"🧠 Building a {days}-day study plan..."):
                plan = generate_study_plan(days)
            if plan:
                with st.expander("📅 View Study Plan", expanded=True):
                    st.markdown(plan)


def render_bonus_section():
    st.subheader("✨ Bonus Tools")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        eli10_clicked = st.button("🧒 Explain Like I'm 10")
    with col2:
        tips_clicked = st.button("🎯 Exam Tips")
    with col3:
        defs_clicked = st.button("📖 Important Definitions")
    with col4:
        formulas_clicked = st.button("➗ Important Formulas")

    if st.session_state.retriever is None and (
        eli10_clicked or tips_clicked or defs_clicked or formulas_clicked
    ):
        st.error("⚠️ Please upload and process a PDF first.")
        return

    if eli10_clicked:
        with st.spinner("🧠 Simplifying the material..."):
            result = generate_eli10()
        if result:
            with st.expander("🧒 Explain Like I'm 10", expanded=True):
                st.markdown(result)

    if tips_clicked:
        with st.spinner("🧠 Preparing exam tips..."):
            result = generate_exam_tips()
        if result:
            with st.expander("🎯 Exam Tips", expanded=True):
                st.markdown(result)

    if defs_clicked:
        with st.spinner("🧠 Extracting definitions..."):
            result = generate_definitions()
        if result:
            with st.expander("📖 Important Definitions", expanded=True):
                st.markdown(result)

    if formulas_clicked:
        with st.spinner("🧠 Extracting formulas..."):
            result = generate_formulas()
        if result:
            with st.expander("➗ Important Formulas", expanded=True):
                st.markdown(result)


# =========================================================
# MAIN APP
# =========================================================
def main():
    st.title("📚 Adaptive Study Agent")
    st.caption("An AI-powered RAG study assistant — upload PDFs and learn smarter.")

    render_sidebar()

    render_upload_section()
    st.divider()

    render_qa_section()
    st.divider()

    render_summary_section()
    st.divider()

    render_quiz_section()
    st.divider()

    render_flashcard_section()
    st.divider()

    render_study_plan_section()
    st.divider()

    render_bonus_section()


if __name__ == "__main__":
    main()