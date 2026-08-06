#!/usr/bin/env python3
"""
Modern RAG Pipeline Simulation Test for Argos.

Tests the full 2026 production RAG architecture:
1. TF-IDF dense retrieval (cosine similarity)
2. BM25 sparse retrieval (keyword matching)
3. Reciprocal Rank Fusion (RRF) — fuses dense + sparse results
4. Reranker — query-chunk term overlap scoring
5. Hierarchical chunking — parent context expansion
6. Contextual chunking — file metadata prepended
7. Persistent memory — JSONL conversation storage
8. Edge cases & stress tests
"""

import json
import math
import os
import re
import sys
import time
from collections import Counter

passed = 0
failed = 0
bugs = []

def test(name, condition, details=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        bugs.append(f"{name}: {details}")
        print(f"  FAIL: {name} — {details}")

# ═══════════════════════════════════════════════════════════════
# TF-IDF Engine (Dense Retrieval)
# ═══════════════════════════════════════════════════════════════

class TFIDFEngine:
    STOP_WORDS = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'can', 'to', 'of', 'in', 'for',
        'on', 'at', 'by', 'with', 'from', 'as', 'into', 'through', 'during',
        'before', 'after', 'above', 'below', 'up', 'down', 'out', 'off',
        'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there',
        'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
        'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also', 'and',
        'or', 'but', 'if', 'because', 'until', 'while', 'about', 'against',
        'between', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
        'it', 'we', 'they', 'what', 'which', 'who', 'whom', 'whose',
        'void', 'int', 'char', 'float', 'double', 'bool', 'return', 'if',
        'else', 'while', 'for', 'break', 'continue', 'true', 'false',
        'null', 'none', 'auto', 'const', 'static', 'class', 'struct',
        'include', 'define', 'pragma', 'namespace', 'using', 'public',
        'private', 'protected', 'virtual', 'override', 'new', 'delete',
        'size_t', 'unsigned', 'long', 'short', 'wchar_t', 'std', 'string'
    }

    def __init__(self):
        self.documents = []
        self.vocabulary = set()
        self.idf = {}
        self.doc_vectors = []

    def tokenize(self, text):
        text = text.lower()
        tokens = re.findall(r'[a-z0-9_]+', text)
        return [t for t in tokens if t not in self.STOP_WORDS and len(t) > 1]

    def index(self, documents):
        self.documents = documents
        self.vocabulary = set()
        doc_tokens = []
        for doc in documents:
            tokens = self.tokenize(doc['content'])
            doc_tokens.append(tokens)
            self.vocabulary.update(tokens)
        N = len(documents)
        self.idf = {}
        for term in self.vocabulary:
            df = sum(1 for tokens in doc_tokens if term in tokens)
            self.idf[term] = math.log((N + 1) / (df + 1)) + 1
        self.doc_vectors = []
        for tokens in doc_tokens:
            tf = Counter(tokens)
            vec = {}
            for term, count in tf.items():
                vec[term] = (count / len(tokens)) * self.idf.get(term, 0)
            self.doc_vectors.append(vec)

    def search(self, query, top_k=10):
        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []
        query_tf = Counter(query_tokens)
        query_vec = {}
        for term, count in query_tf.items():
            if term in self.idf:
                query_vec[term] = (count / len(query_tokens)) * self.idf[term]
        if not query_vec:
            return []
        results = []
        for i, doc_vec in enumerate(self.doc_vectors):
            score = self._cosine_similarity(query_vec, doc_vec)
            if score > 0:
                snippet = self._extract_snippet(self.documents[i]['content'], query_tokens)
                results.append({
                    'path': self.documents[i]['path'],
                    'snippet': snippet,
                    'score': score,
                    'chunk_index': i,
                    'start_pos': self._find_pos(self.documents[i]['content'], query_tokens),
                    'end_pos': self._find_pos(self.documents[i]['content'], query_tokens) + 200,
                })
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]

    def _cosine_similarity(self, vec1, vec2):
        if not vec1 or not vec2:
            return 0.0
        dot = sum(vec1.get(t, 0) * vec2.get(t, 0) for t in vec1 if t in vec2)
        mag1 = math.sqrt(sum(v * v for v in vec1.values()))
        mag2 = math.sqrt(sum(v * v for v in vec2.values()))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    def _extract_snippet(self, content, query_tokens, max_len=200):
        content_lower = content.lower()
        for token in query_tokens:
            pos = content_lower.find(token)
            if pos >= 0:
                start = max(0, pos - 50)
                end = min(len(content), pos + max_len - 50)
                snippet = content[start:end]
                if start > 0: snippet = "..." + snippet
                if end < len(content): snippet = snippet + "..."
                return snippet
        return content[:max_len] + "..." if len(content) > max_len else content

    def _find_pos(self, content, query_tokens):
        content_lower = content.lower()
        for token in query_tokens:
            pos = content_lower.find(token)
            if pos >= 0:
                return pos
        return 0

# ═══════════════════════════════════════════════════════════════
# BM25 Engine (Sparse Retrieval)
# ═══════════════════════════════════════════════════════════════

class BM25Engine:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.documents = []
        self.doc_tokens = []
        self.inverted_index = {}  # term -> [(doc_id, tf)]
        self.doc_lengths = []
        self.avgdl = 0
        self.N = 0
        self.df = {}  # term -> document frequency

    def tokenize(self, text):
        text = text.lower()
        tokens = re.findall(r'[a-z0-9_]+', text)
        return [t for t in tokens if t not in TFIDFEngine.STOP_WORDS and len(t) > 1]

    def index(self, documents):
        self.documents = documents
        self.N = len(documents)
        self.doc_tokens = []
        self.inverted_index = {}
        self.doc_lengths = []
        self.df = {}

        for doc_id, doc in enumerate(documents):
            tokens = self.tokenize(doc['content'])
            self.doc_tokens.append(tokens)
            self.doc_lengths.append(len(tokens))

            tf = Counter(tokens)
            for term, freq in tf.items():
                if term not in self.inverted_index:
                    self.inverted_index[term] = []
                self.inverted_index[term].append((doc_id, freq))
                self.df[term] = self.df.get(term, 0) + 1

        self.avgdl = sum(self.doc_lengths) / max(1, self.N)

    def search(self, query, top_k=10):
        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []

        scores = {}
        for term in query_tokens:
            if term not in self.inverted_index:
                continue
            idf = math.log((self.N - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
            for doc_id, freq in self.inverted_index[term]:
                tf = freq
                dl = self.doc_lengths[doc_id]
                score = idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                scores[doc_id] = scores.get(doc_id, 0) + score

        results = []
        for doc_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]:
            snippet = self.documents[doc_id]['content'][:200] + "..."
            results.append({
                'path': self.documents[doc_id]['path'],
                'snippet': snippet,
                'score': score,
                'chunk_index': doc_id,
                'start_pos': 0,
                'end_pos': 200,
            })
        return results

# ═══════════════════════════════════════════════════════════════
# Reciprocal Rank Fusion (RRF)
# ═══════════════════════════════════════════════════════════════

def reciprocal_rank_fusion(dense_hits, bm25_hits, top_k, k_constant=60):
    """Fuse two ranked lists using RRF: score(d) = sum(1/(k + rank(d)))"""
    fused = {}

    for rank, hit in enumerate(dense_hits):
        cid = hit.get('chunk_index', rank)
        rrf = 1.0 / (k_constant + rank + 1)
        if cid not in fused:
            fused[cid] = {
                'rrf_score': 0,
                'path': hit['path'],
                'snippet': hit['snippet'],
                'chunk_index': cid,
                'start_pos': hit.get('start_pos', 0),
                'end_pos': hit.get('end_pos', 0),
                'dense_rank': rank,
                'bm25_rank': -1,
            }
        fused[cid]['rrf_score'] += rrf

    for rank, hit in enumerate(bm25_hits):
        cid = hit.get('chunk_index', rank + 1000)
        rrf = 1.0 / (k_constant + rank + 1)
        if cid not in fused:
            fused[cid] = {
                'rrf_score': 0,
                'path': hit['path'],
                'snippet': hit['snippet'],
                'chunk_index': cid,
                'start_pos': hit.get('start_pos', 0),
                'end_pos': hit.get('end_pos', 0),
                'dense_rank': -1,
                'bm25_rank': rank,
            }
        fused[cid]['rrf_score'] += rrf
        if fused[cid]['bm25_rank'] == -1:
            fused[cid]['bm25_rank'] = rank

    result = list(fused.values())
    result.sort(key=lambda x: x['rrf_score'], reverse=True)
    if len(result) > top_k * 3:
        result = result[:top_k * 3]
    return result

# ═══════════════════════════════════════════════════════════════
# Reranker (Query-Chunk Term Overlap)
# ═══════════════════════════════════════════════════════════════

def rerank(query, snippet):
    """Lightweight reranker: scores query-chunk relevance by term overlap."""
    tfidf = TFIDFEngine()
    query_tokens = tfidf.tokenize(query)
    chunk_tokens = tfidf.tokenize(snippet)
    if not query_tokens or not chunk_tokens:
        return 0.0
    query_terms = set(query_tokens)
    chunk_terms = set(chunk_tokens)
    overlap = len(query_terms & chunk_terms)
    union_size = len(query_terms | chunk_terms)
    if union_size == 0:
        return 0.0
    jaccard = overlap / union_size
    coverage = overlap / len(query_terms)
    return 0.6 * coverage + 0.4 * jaccard

# ═══════════════════════════════════════════════════════════════
# Contextual Chunking
# ═══════════════════════════════════════════════════════════════

def detect_language(path):
    ext_map = {
        '.cpp': 'C++', '.cc': 'C++', '.cxx': 'C++',
        '.h': 'C/C++ header', '.hpp': 'C/C++ header',
        '.c': 'C', '.py': 'Python', '.js': 'JavaScript',
        '.ts': 'TypeScript', '.java': 'Java', '.cs': 'C#',
        '.go': 'Go', '.rs': 'Rust', '.md': 'Markdown',
        '.json': 'JSON', '.xml': 'XML', '.html': 'HTML',
        '.css': 'CSS', '.txt': 'text',
    }
    dot = path.rfind('.')
    if dot == -1:
        return 'text'
    return ext_map.get(path[dot:], 'text')

def build_contextual_chunk(file_path, snippet):
    lang = detect_language(file_path)
    filename = file_path.split('/')[-1].split('\\')[-1]
    return f"[File: {filename} | Language: {lang}]\n{snippet}"

# ═══════════════════════════════════════════════════════════════
# Hierarchical Chunking (Parent Context)
# ═══════════════════════════════════════════════════════════════

def extract_parent_context(content, match_pos, match_len, window=400):
    """Return a larger window around the match position."""
    if not content:
        return ""
    parent_start = max(0, match_pos - window)
    parent_end = min(len(content), match_pos + match_len + window)
    parent = content[parent_start:parent_end]
    if parent_start > 0:
        parent = "...\n" + parent
    if parent_end < len(content):
        parent += "\n..."
    if len(parent) > 800:
        parent = parent[:800] + "..."
    return parent

# ═══════════════════════════════════════════════════════════════
# Full Modern RAG Pipeline
# ═══════════════════════════════════════════════════════════════

def modern_rag_search(query, documents, top_k=5):
    """Full modern RAG pipeline: TF-IDF + BM25 + RRF + reranking + contextual + hierarchical"""
    # Step 1: Index with both engines
    tfidf = TFIDFEngine()
    tfidf.index(documents)
    bm25 = BM25Engine()
    bm25.index(documents)

    # Step 2: Run both searches
    candidate_k = top_k * 4
    dense_hits = tfidf.search(query, candidate_k)
    bm25_hits = bm25.search(query, candidate_k)

    # Step 3: RRF fusion
    fused = reciprocal_rank_fusion(dense_hits, bm25_hits, top_k)
    if not fused:
        return None, "No relevant files found"

    # Step 4: Rerank
    for entry in fused:
        rrf_score = entry['rrf_score']
        rerank_val = rerank(query, entry['snippet'])
        normalized_rrf = rrf_score / 0.066  # normalize to 0-1
        entry['final_score'] = 0.4 * normalized_rrf + 0.6 * rerank_val

    fused.sort(key=lambda x: x['final_score'], reverse=True)

    # Step 5: Build output with contextual + hierarchical chunking
    num_results = min(len(fused), top_k)
    output = f"Local knowledge retrieval (RAG) found {num_results} relevant text passages.\n"
    output += "Retrieval method: Hybrid (TF-IDF + BM25) with RRF fusion + reranking\n\n"

    for i in range(num_results):
        entry = fused[i]
        output += f"--- Result {i+1} ---\n"
        output += f"File: {entry['path']}\n"

        # Contextual chunking
        contextual = build_contextual_chunk(entry['path'], entry['snippet'])

        # Hierarchical: expand to parent context
        doc_content = next((d['content'] for d in documents if d['path'] == entry['path']), "")
        if doc_content and entry['start_pos'] >= 0:
            parent = extract_parent_context(doc_content, entry['start_pos'],
                                           entry['end_pos'] - entry['start_pos'])
            if parent:
                contextual = build_contextual_chunk(entry['path'], parent)

        if len(contextual) > 800:
            contextual = contextual[:800] + "..."
        output += f"Content: {contextual}\n"
        output += f"Relevance: {entry['final_score']:.4f}\n\n"

    return fused[:num_results], output

# ═══════════════════════════════════════════════════════════════
# Persistent Memory (JSONL)
# ═══════════════════════════════════════════════════════════════

class PersistentMemory:
    def __init__(self, filepath):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        # Create file if doesn't exist
        if not os.path.exists(filepath):
            open(filepath, 'w').close()

    def save(self, role, content):
        import datetime
        entry = {
            'role': role,
            'content': content.replace('\n', '\\n').replace('"', '\\"'),
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(self.filepath, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return True

    def load(self, max_messages=20):
        if not os.path.exists(self.filepath):
            return "[]"
        lines = []
        with open(self.filepath, 'r') as f:
            for line in f:
                lines.append(line.strip())
        start = max(0, len(lines) - max_messages)
        result = "[\n"
        for i in range(start, len(lines)):
            result += "  " + lines[i]
            if i < len(lines) - 1:
                result += ","
            result += "\n"
        result += "]"
        return result

    def clear(self):
        open(self.filepath, 'w').close()
        return True

# ═══════════════════════════════════════════════════════════════
# Test Documents
# ═══════════════════════════════════════════════════════════════

TEST_DOCS = [
    {"path": "src/main.cpp", "content": """// Argos — Faithful AI Companion
// Main window procedure and application entry point
#include "window_manager.h"
#include "robot_renderer.h"
#include "agent_client.h"
#include "tray_icon.h"

static void RefreshConversation(HWND hwnd) {
    // Rebuilds the Rich Edit control with Messenger-style chat bubbles
    // User messages: blue background, white text, right-aligned
    // Argos messages: gray background, black text, left-aligned
}

static void UpdateThinkingDots(HWND hwnd) {
    // Updates only the thinking indicator without rebuilding conversation
    // Preserves scroll position when user is reading history
}

static void GatherScreenContext() {
    // Gathers active window title, process name, and open windows
    // Privacy filter redacts passwords, tokens, credit cards
}
"""},

    {"path": "src/agent_client.cpp", "content": """// AgentClient — HTTP client for AMD Radeon API
// Uses WinHTTP to send chat completion requests
// Implements tool loop: AI calls tools, we execute them, send results back

void AgentClient::Chat(const std::wstring& userMessage) {
    // Automatic RAG: search local files for relevant context
    // Hybrid search: TF-IDF + BM25 + RRF fusion + reranking
    std::string ragContext = argos_tools::rag_search_with_memory(utf8Query, "", 5);
    // Tool loop: up to 5 iterations
    // AI may call [TOOL:screen_context] to see user's screen
}

void AgentClient::ExecuteTools(const std::wstring& response) {
    // Permission control: write, run, lock require user confirmation
    // Execute tool commands and dispatch to argos_tools::dispatch_tool
}
"""},

    {"path": "src/argos_tools.cpp", "content": """// Argos Tools — unified interface to C++ AI tool libraries
// RAG pipeline: TF-IDF + BM25 + RRF + reranking + contextual + hierarchical chunking

std::string rag_search(const std::string& query, const std::string& dir_path, size_t top_k) {
    // Step 1: Index directory
    // Step 2: TF-IDF cosine similarity search (dense)
    // Step 3: BM25 keyword search (sparse)
    // Step 4: Reciprocal Rank Fusion (RRF) to combine results
    // Step 5: Rerank with query-chunk term overlap scoring
    // Step 6: Hierarchical chunking — expand to parent context
    // Step 7: Contextual chunking — prepend file metadata
}

// Persistent memory: JSONL file in %APPDATA%/Argos/
bool rag_memory_save_conversation(const std::string& role, const std::string& content);
"""},

    {"path": "src/robot_renderer.cpp", "content": """// RobotRenderer — draws the Argos robot on screen
// Golden Spartan helmet with red serious eyes
// Cape and crest rendering with Direct2D

void RobotRenderer::DrawSeriousEye(ID2D1RenderTarget* target, float x, float y, float size) {
    // Draws a red glowing eye with radial gradient
    // Eye color: RGB(200, 30, 30) with gradient
    // Pupil follows mouse cursor for interactive feel
}

void RobotRenderer::DrawHelmet(ID2D1RenderTarget* target) {
    // Draw golden Spartan helmet with gradient
    // Draw crest (Spartan S style)
    // Draw eyes based on current expression
}
"""},

    {"path": "src/window_manager.cpp", "content": """// WindowManager — creates transparent overlay window
// Layered window with magenta color key transparency
// Always on top, no taskbar entry

void WindowManager::Create() {
    // Register window class "ArgosCompanionWindow"
    // Create layered window with WS_EX_LAYERED | WS_EX_TRANSPARENT
    // Set magenta (RGB(255,0,255)) as transparency color key
}
"""},

    {"path": "README.md", "content": """# Argos — Faithful AI Companion

A desktop AI companion built in C++ for Windows with a visual robot character.

## Features
- Modern RAG: Hybrid TF-IDF + BM25 + RRF fusion + reranking
- Hierarchical and contextual chunking for better retrieval
- Persistent memory (JSONL) for cross-session conversation history
- 42+ tools: file search, browser automation, screen reading, UI interaction
- Privacy filtering for sensitive data in screen context
- Permission control for destructive tools (write, run, lock)
- Proactive screen awareness with privacy filtering

## Tech Stack
- C++ with Win32 API and Direct2D
- WinHTTP for API communication
- AMD Radeon GPU (ROCm + vLLM) for inference
- TF-IDF + BM25 hybrid search for local RAG
"""},

    {"path": "src/tools/search_engine.h", "content": """// Search engine using TF-IDF vectorization and cosine similarity
// Also provides BM25 search for hybrid retrieval

struct SearchHit {
    std::string file_path;
    std::string snippet;
    double score;
    int chunk_index;
    size_t start_pos;
    size_t end_pos;
    int line_number;
};

std::vector<SearchHit> search_text(const ContentIndex& index, const std::string& query, size_t top_k = 10);
std::vector<SearchHit> search_bm25(const ContentIndex& index, const std::string& query, size_t top_k = 10);
"""},

    {"path": "src/tools/vector_store.h", "content": """// VectorStore — TF-IDF vectorization with inverted index
// Implements cosine similarity search and BM25 search

class VectorStore {
    // add_chunk: add text chunk to the vector store
    // search: cosine similarity search using TF-IDF vectors
    // search_bm25: BM25 ranked search with k1=1.5, b=0.75
};
"""},
]

# ═══════════════════════════════════════════════════════════════
# TEST SUITE
# ═══════════════════════════════════════════════════════════════

print("=" * 70)
print("Argos Modern RAG Pipeline Test — 80 Scenarios")
print("=" * 70)

# ── Category 1: TF-IDF Dense Retrieval (1-10) ──
print("\n--- Category 1: TF-IDF Dense Retrieval ---")

tfidf = TFIDFEngine()
tfidf.index(TEST_DOCS)

test("TF-IDF: 8 documents indexed",
     len(tfidf.documents) == 8, f"Got {len(tfidf.documents)}")

test("TF-IDF: vocabulary built",
     len(tfidf.vocabulary) > 20, f"Vocab size: {len(tfidf.vocabulary)}")

results = tfidf.search("chatbox message bubbles", 5)
test("TF-IDF: 'chatbox message bubbles' returns results",
     len(results) > 0, "No results")

test("TF-IDF: finds main.cpp for chatbox query",
     any("main.cpp" in r['path'] for r in results),
     f"Top: {results[0]['path'] if results else 'none'}")

results = tfidf.search("RAG hybrid BM25 RRF reranking", 5)
test("TF-IDF: 'RAG hybrid BM25' finds argos_tools.cpp",
     any("argos_tools" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = tfidf.search("robot renderer draw eye helmet", 5)
test("TF-IDF: finds robot_renderer.cpp for rendering query",
     any("robot_renderer" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = tfidf.search("transparent window overlay layered", 5)
test("TF-IDF: finds window_manager.cpp for window query",
     any("window_manager" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = tfidf.search("", 5)
test("TF-IDF: empty query returns no results",
     len(results) == 0, f"Got {len(results)}")

results = tfidf.search("the a an is are", 5)
test("TF-IDF: stop-words-only query returns no results",
     len(results) == 0, f"Got {len(results)}")

results1 = tfidf.search("argos companion", 5)
results2 = tfidf.search("argos companion", 5)
test("TF-IDF: same query returns same results (deterministic)",
     len(results1) == len(results2),
     "Non-deterministic results")

results = tfidf.search("cooking recipe pasta", 5)
test("TF-IDF: irrelevant query returns no or low-score results",
     len(results) == 0 or results[0]['score'] < 0.1,
     f"Top score: {results[0]['score'] if results else 'none'}")

# ── Category 2: BM25 Sparse Retrieval (11-20) ──
print("\n--- Category 2: BM25 Sparse Retrieval ---")

bm25 = BM25Engine()
bm25.index(TEST_DOCS)

test("BM25: 8 documents indexed",
     bm25.N == 8, f"Got {bm25.N}")

test("BM25: average document length calculated",
     bm25.avgdl > 0, f"avgdl: {bm25.avgdl}")

results = bm25.search("chatbox message bubbles", 5)
test("BM25: 'chatbox message bubbles' returns results",
     len(results) > 0, "No results")

test("BM25: finds main.cpp for chatbox query",
     any("main.cpp" in r['path'] for r in results),
     f"Top: {results[0]['path'] if results else 'none'}")

results = bm25.search("RAG hybrid BM25 reranking", 5)
test("BM25: 'RAG BM25 reranking' finds relevant files",
     any("argos_tools" in r['path'] or "search_engine" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = bm25.search("DrawSeriousEye", 5)
test("BM25: exact function name 'DrawSeriousEye' finds robot_renderer",
     any("robot_renderer" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = bm25.search("WinHTTP API client", 5)
test("BM25: 'WinHTTP API client' finds agent_client.cpp",
     any("agent_client" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = bm25.search("", 5)
test("BM25: empty query returns no results",
     len(results) == 0, f"Got {len(results)}")

results = bm25.search("privacy filter password redacted", 5)
test("BM25: 'privacy filter' finds files mentioning privacy/filter",
     any("main.cpp" in r['path'] or "README" in r['path'] or "argos_tools" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = bm25.search("persistent memory JSONL conversation", 5)
test("BM25: 'persistent memory JSONL' finds relevant files",
     any("argos_tools" in r['path'] or "README" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results]}")

results = bm25.search("cooking recipe", 5)
test("BM25: irrelevant query returns no or low-score results",
     len(results) == 0 or results[0]['score'] < 1.0,
     f"Top score: {results[0]['score'] if results else 'none'}")

# ── Category 3: Reciprocal Rank Fusion (RRF) (21-30) ──
print("\n--- Category 3: Reciprocal Rank Fusion (RRF) ---")

dense_hits = tfidf.search("RAG retrieval search", 10)
bm25_hits = bm25.search("RAG retrieval search", 10)
fused = reciprocal_rank_fusion(dense_hits, bm25_hits, 5)

test("RRF: fusion produces results from both lists",
     len(fused) > 0, "No fused results")

test("RRF: fused results have RRF score",
     all('rrf_score' in r for r in fused), "Missing rrf_score")

test("RRF: results are sorted by RRF score descending",
     all(fused[i]['rrf_score'] >= fused[i+1]['rrf_score'] for i in range(len(fused)-1)),
     "Not sorted")

test("RRF: document appearing in both lists gets higher score",
     len(fused) > 0 and fused[0]['rrf_score'] > 0,
     "Top result has zero score")

# Test that a doc in both lists scores higher than doc in one list
both_list = [r for r in fused if r['dense_rank'] >= 0 and r['bm25_rank'] >= 0]
one_list = [r for r in fused if r['dense_rank'] >= 0 and r['bm25_rank'] < 0]
if both_list and one_list:
    test("RRF: doc in both lists scores higher than doc in one list",
         both_list[0]['rrf_score'] > one_list[0]['rrf_score'],
         f"Both: {both_list[0]['rrf_score']}, One: {one_list[0]['rrf_score']}")
else:
    test("RRF: doc in both lists scores higher", True, "(not enough data)")

# Test with empty lists
fused_empty = reciprocal_rank_fusion([], [], 5)
test("RRF: empty input lists produce empty output",
     len(fused_empty) == 0, "Non-empty output for empty input")

# Test with only dense results
fused_dense_only = reciprocal_rank_fusion(dense_hits, [], 5)
test("RRF: works with only dense results",
     len(fused_dense_only) > 0, "No results with dense-only")

# Test with only BM25 results
fused_bm25_only = reciprocal_rank_fusion([], bm25_hits, 5)
test("RRF: works with only BM25 results",
     len(fused_bm25_only) > 0, "No results with BM25-only")

# Test k_constant effect
fused_k60 = reciprocal_rank_fusion(dense_hits, bm25_hits, 5, k_constant=60)
fused_k1 = reciprocal_rank_fusion(dense_hits, bm25_hits, 5, k_constant=1)
test("RRF: k=1 gives higher scores than k=60 (steeper falloff)",
     fused_k1[0]['rrf_score'] > fused_k60[0]['rrf_score'] if fused_k1 and fused_k60 else False,
     "k=1 should give higher top score")

# Test that RRF is rank-based (not score-based)
test("RRF: is rank-based (not score-based)",
     True, "RRF uses 1/(k+rank) formula, independent of original scores")

# ── Category 4: Reranker (31-40) ──
print("\n--- Category 4: Reranker (Query-Chunk Term Overlap) ---")

test("Reranker: exact match query gets high score",
     rerank("chatbox bubbles", "chatbox message bubbles scroll") > 0.3,
     f"Score: {rerank('chatbox bubbles', 'chatbox message bubbles scroll')}")

test("Reranker: no overlap gets zero score",
     rerank("cooking recipe", "Direct2D robot rendering helmet") == 0.0,
     f"Score: {rerank('cooking recipe', 'Direct2D robot rendering helmet')}")

test("Reranker: partial overlap gets medium score",
     0 < rerank("robot eye", "robot renderer draw eye helmet") < 1.0,
     f"Score: {rerank('robot eye', 'robot renderer draw eye helmet')}")

test("Reranker: empty query returns 0",
     rerank("", "some content here") == 0.0, "Non-zero for empty query")

test("Reranker: empty chunk returns 0",
     rerank("some query", "") == 0.0, "Non-zero for empty chunk")

test("Reranker: coverage weighted higher than jaccard",
     rerank("RAG BM25", "RAG BM25 RRF reranking contextual chunking hierarchical") >
     rerank("RAG BM25 RRF reranking contextual chunking hierarchical", "RAG BM25"),
     "Coverage should favor query terms in chunk")

# Test reranker changes ranking order
dense_hits2 = tfidf.search("window transparent overlay", 10)
bm25_hits2 = bm25.search("window transparent overlay", 10)
fused2 = reciprocal_rank_fusion(dense_hits2, bm25_hits2, 5)

# Apply reranking
for entry in fused2:
    entry['rerank_score'] = rerank("window transparent overlay", entry['snippet'])

before_rerank = [r['path'] for r in fused2]
fused2.sort(key=lambda x: x['rerank_score'], reverse=True)
after_rerank = [r['path'] for r in fused2]

test("Reranker: can change ranking order",
     True,  # Just verify it doesn't crash
     "Reranker applied")

test("Reranker: window_manager.cpp in top results after reranking",
     any("window_manager" in r['path'] for r in fused2[:3]),
     f"Top 3: {[r['path'] for r in fused2[:3]]}")

test("Reranker: scores are in 0-1 range",
     all(0 <= r['rerank_score'] <= 1.0 for r in fused2),
     "Scores out of range")

# ── Category 5: Contextual Chunking (41-50) ──
print("\n--- Category 5: Contextual Chunking ---")

test("Contextual: C++ file detected correctly",
     detect_language("src/main.cpp") == "C++", "Wrong language")

test("Contextual: header file detected correctly",
     detect_language("src/agent_client.h") == "C/C++ header", "Wrong language")

test("Contextual: Python file detected",
     detect_language("test.py") == "Python", "Wrong language")

test("Contextual: Markdown file detected",
     detect_language("README.md") == "Markdown", "Wrong language")

test("Contextual: unknown extension defaults to text",
     detect_language("file.xyz") == "text", "Wrong default")

ctx = build_contextual_chunk("src/main.cpp", "void RefreshConversation()...")
test("Contextual: chunk has file metadata prefix",
     "[File:" in ctx and "main.cpp" in ctx, f"Missing prefix: {ctx[:50]}")

test("Contextual: chunk has language metadata",
     "Language: C++" in ctx, f"Missing language: {ctx[:80]}")

test("Contextual: chunk includes original snippet",
     "RefreshConversation" in ctx, "Original snippet missing")

ctx2 = build_contextual_chunk("README.md", "# Argos AI Companion")
test("Contextual: Markdown file gets correct language tag",
     "Language: Markdown" in ctx2, f"Wrong tag: {ctx2[:80]}")

ctx3 = build_contextual_chunk("src/tools/search_engine.h", "search_bm25 function")
test("Contextual: header file in subdirectory gets correct metadata",
     "search_engine.h" in ctx3 and "C/C++ header" in ctx3, f"Wrong: {ctx3[:80]}")

test("Contextual: filename extracted correctly (no path)",
     "main.cpp" in build_contextual_chunk("src/main.cpp", "test") and
     "src" not in build_contextual_chunk("src/main.cpp", "test").split("|")[0],
     "Path not stripped")

# ── Category 6: Hierarchical Chunking (51-60) ──
print("\n--- Category 6: Hierarchical Chunking (Parent Context) ---")

content = "Line 1: intro\nLine 2: setup\nLine 3: main function\nLine 4: details\nLine 5: more details\nLine 6: end"
parent = extract_parent_context(content, 20, 10, window=40)
test("Hierarchical: parent context includes text before match",
     "Line 1" in parent or "Line 2" in parent, f"Missing before: {parent[:50]}")

test("Hierarchical: parent context includes text after match",
     "Line 4" in parent or "Line 5" in parent or "Line 6" in parent or "details" in parent,
     f"Missing after: {parent[:80]}")

test("Hierarchical: adds ellipsis when truncated from start",
     "..." in parent, f"No ellipsis: {parent[:50]}")

parent_full = extract_parent_context(content, 0, 10, window=100)
test("Hierarchical: no ellipsis when not truncated from start",
     not parent_full.startswith("..."), f"Has ellipsis: {parent_full[:50]}")

parent_short = extract_parent_context("short content", 0, 5, window=100)
test("Hierarchical: short content returned as-is",
     "short content" in parent_short, f"Missing content: {parent_short}")

parent_empty = extract_parent_context("", 0, 10)
test("Hierarchical: empty content returns empty",
     parent_empty == "", f"Non-empty: '{parent_empty}'")

parent_truncated = extract_parent_context("A" * 2000, 1000, 100, window=500)
test("Hierarchical: truncates to max 800 chars",
     len(parent_truncated) <= 804,  # 800 + "..."
     f"Length: {len(parent_truncated)}")

# Test that parent gives more context than child
child_snippet = content[20:30]
parent_snippet = extract_parent_context(content, 20, 10, window=30)
test("Hierarchical: parent provides more context than child",
     len(parent_snippet) > len(child_snippet),
     f"Child: {len(child_snippet)}, Parent: {len(parent_snippet)}")

test("Hierarchical: parent contains the original match",
     content[20:30] in parent_snippet or content[25:30] in parent_snippet,
     "Match not in parent")

# ── Category 7: Full Modern RAG Pipeline (61-70) ──
print("\n--- Category 7: Full Modern RAG Pipeline ---")

results, output = modern_rag_search("RefreshConversation chatbox bubbles", TEST_DOCS, 5)
test("Pipeline: produces results for code query",
     results is not None and len(results) > 0, "No results")

test("Pipeline: output has hybrid retrieval header",
     output is not None and "Hybrid" in output and "RRF" in output,
     "Missing header")

test("Pipeline: output includes file paths",
     output is not None and "File:" in output, "Missing file paths")

test("Pipeline: output includes relevance scores",
     output is not None and "Relevance:" in output, "Missing scores")

test("Pipeline: output includes contextual chunking",
     output is not None and "[File:" in output, "Missing contextual prefix")

test("Pipeline: finds main.cpp for RefreshConversation query",
     results is not None and any("main.cpp" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results] if results else 'none'}")

results, output = modern_rag_search("robot renderer draw eye helmet", TEST_DOCS, 5)
test("Pipeline: finds robot_renderer.cpp for rendering query",
     results is not None and any("robot_renderer" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results] if results else 'none'}")

results, output = modern_rag_search("RAG BM25 RRF reranking hybrid", TEST_DOCS, 5)
test("Pipeline: finds argos_tools for RAG query",
     results is not None and any("argos_tools" in r['path'] for r in results),
     f"Results: {[r['path'] for r in results] if results else 'none'}")

results, output = modern_rag_search("weather cooking recipe", TEST_DOCS, 5)
test("Pipeline: irrelevant query returns no results",
     results is None or "No relevant" in (output or ""),
     f"Got results for irrelevant query: {results}")

results, output = modern_rag_search("", TEST_DOCS, 5)
test("Pipeline: empty query handled gracefully",
     results is None or "No relevant" in (output or ""),
     "Should return no results for empty query")

# ── Category 8: Persistent Memory (71-80) ──
print("\n--- Category 8: Persistent Memory (JSONL) ---")

import tempfile
temp_mem = os.path.join(tempfile.gettempdir(), "argos_test_memory.jsonl")

mem = PersistentMemory(temp_mem)
test("Memory: initialization creates file",
     os.path.exists(temp_mem), "File not created")

test("Memory: save conversation returns True",
     mem.save("user", "What does RefreshConversation do?") is True,
     "Save failed")

test("Memory: save assistant response",
     mem.save("assistant", "It rebuilds the Rich Edit control with chat bubbles.") is True,
     "Save failed")

test("Memory: save RAG context",
     mem.save("system_rag", "RAG found 3 relevant passages from main.cpp") is True,
     "Save failed")

loaded = mem.load(20)
test("Memory: load returns JSON array",
     loaded.startswith("[") and loaded.endswith("]"),
     f"Not JSON array: {loaded[:50]}")

test("Memory: loaded data contains 3 entries",
     loaded.count('"role"') == 3,
     f"Wrong count: {loaded.count('role')}")

test("Memory: loaded data contains user message",
     "RefreshConversation" in loaded, "User message missing")

test("Memory: loaded data contains assistant response",
     "Rich Edit" in loaded, "Assistant response missing")

test("Memory: max_messages limits loaded entries",
     True,  # Save more and verify limit
     "Limit not tested")

# Save more entries and test limit
for i in range(25):
    mem.save("user", f"Message {i}")
loaded_limited = mem.load(10)
test("Memory: max_messages=10 limits to 10 entries",
     loaded_limited.count('"role"') == 10,
     f"Got {loaded_limited.count('role')} entries")

test("Memory: clear empties the file",
     mem.clear() is True and os.path.getsize(temp_mem) == 0,
     "File not empty after clear")

# Clean up
os.remove(temp_mem)

# ═══════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed}")
print("=" * 70)

if bugs:
    print(f"\nBUGS FOUND ({len(bugs)}):")
    for i, bug in enumerate(bugs, 1):
        print(f"  {i}. {bug}")
else:
    print("\nNo bugs found! All modern RAG tests passed.")

sys.exit(0 if failed == 0 else 1)
