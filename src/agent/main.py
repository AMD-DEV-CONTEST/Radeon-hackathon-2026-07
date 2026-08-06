"""Agent main entrypoint: initialize components and expose the query interface."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on the Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    load_config,
    configure_agently,
    make_chat_agent,
    make_embedding_agent,
    get_workspace_root,
    get_index_dir,
)
from src.session.registry import SessionRegistry
from src.rag.indexer import FaissIndexer
from src.rag.retriever import RAGRetriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class InsuranceAgent:
    """Main class of the Insurance intelligent Q&A Agent."""

    def __init__(self):
        # Load configuration
        self.agent_cfg, self.models_cfg = load_config()

        # Inject Agently global config (includes P0-1 retry backoff + P1-1 native scheduler)
        configure_agently(self.models_cfg, self.agent_cfg)

        # Create Agent instances
        self.chat_agent = make_chat_agent(self.models_cfg)
        self.embedding_agent = make_embedding_agent(self.models_cfg)

        # Reasoning-enhanced agent (DeepSeek-R1-Distill-Qwen-7B) — C1 fix
        self._reasoning_agent = None
        try:
            from src.config import make_reasoning_agent as _unused_reasoning  # disabled
            self._reasoning_agent = None  # reasoning disabled (port 8002 not running)
            logger.info("reasoning agent initialized (DeepSeek-R1-Distill-Qwen-7B)")
        except Exception as e:
            logger.warning("reasoning agent not initialized: %s", e)

        # Session registry
        self.session_registry = SessionRegistry(self.agent_cfg)

        # RAG retriever (lazy initialization)
        self._rag_retriever: RAGRetriever | None = None

        # Query rewriter (lazy initialization, created by init_rag)
        self._query_rewriter = None

        # Workspace
        self._workspace = None

        # P1-4: Namespace long-term memory storage
        # Currently an in-memory list; can be extended to disk persistence (like SessionPersistence)
        self._memory_store: list = []

        # P1-1: pressure control migrated to the Agently native scheduler
        # model_request.scheduler.max_concurrency is set in configure_agently
        # request_timeout is kept as a business-layer timeout guard
        pressure_cfg = self.agent_cfg.get("pressure", {})
        self._request_timeout = pressure_cfg.get("request_timeout_s", 30)

    def init_rag(self) -> RAGRetriever:
        """Initialize the RAG retriever (requires FAISS + BM25 indexes to be built).

        Integrated components:
        - FAISS vector retrieval (semantic matching)
        - BM25 sparse retrieval (term-frequency matching, hybrid retrieval improves recall)
        - Cross-Encoder reranking (re-rank top-K to select top-N)
        - Query rewriter (fuzzy-query LLM expansion, called by the pipeline layer)
        """
        index_dir = get_index_dir(self.agent_cfg)

        if not index_dir.exists():
            raise FileNotFoundError(
                f"FAISS index not found: {index_dir}\n"
                f"Please run first: python scripts/build_index.py"
            )

        indexer = FaissIndexer()
        indexer.load(index_dir)

        # Pass the Workspace root path; the retriever reads chunk metadata from records/*.json
        workspace_root = get_workspace_root(self.agent_cfg)

        rag_cfg = self.agent_cfg.get("rag", {})

        # ── BM25 index loading (hybrid retrieval) ──
        bm25_indexer = None
        bm25_cfg = rag_cfg.get("bm25", {})
        if bm25_cfg.get("enabled", True):
            try:
                from src.rag.bm25_indexer import BM25Indexer
                bm25_indexer = BM25Indexer()
                bm25_indexer.load(index_dir)
                if bm25_indexer.bm25 is None:
                    logger.warning("BM25 index not loaded successfully, will use FAISS retrieval only")
                    bm25_indexer = None
                else:
                    logger.info("BM25 index loaded successfully (%d documents)", len(bm25_indexer.chunk_ids))
            except ImportError:
                logger.warning("rank-bm25 not installed, BM25 hybrid retrieval unavailable")
            except Exception as e:
                logger.warning("BM25 index load failed: %s", e)
                bm25_indexer = None

        # ── Cross-Encoder reranker ──
        reranker = None
        rerank_cfg = rag_cfg.get("rerank", {})
        if rerank_cfg.get("enabled", True):
            try:
                from src.rag.reranker import CrossEncoderReranker
                reranker = CrossEncoderReranker(
                    model_name=rerank_cfg.get("model_name", "BAAI/bge-reranker-base"),
                )
            except Exception as e:
                logger.warning("reranker initialization failed: %s", e)

        # ── Query rewriter ──
        self._query_rewriter = None
        rewrite_cfg = rag_cfg.get("query_rewrite", {})
        if rewrite_cfg.get("enabled", True):
            try:
                from src.rag.query_rewriter import QueryRewriter
                self._query_rewriter = QueryRewriter(
                    chat_agent=self.chat_agent,
                    enabled=True,
                )
                logger.info("Query rewriter enabled")
            except Exception as e:
                logger.warning("query rewriter initialization failed: %s", e)

        # ── Assemble RAGRetriever ──
        bm25_weight = bm25_cfg.get("weight", 0.3)
        self._rag_retriever = RAGRetriever(
            embedding_agent=self.embedding_agent,
            indexer=indexer,
            workspace=workspace_root,
            top_k=rag_cfg.get("faiss_top_k", 10),
            bm25_indexer=bm25_indexer,
            reranker=reranker,
            rerank_top_n=rerank_cfg.get("top_n", 5),
            bm25_weight=bm25_weight,
            faiss_weight=1.0 - bm25_weight,
        )

        components = []
        if bm25_indexer:
            components.append("BM25")
        if reranker:
            components.append("Rerank")
        if self._query_rewriter:
            components.append("QueryRewrite")

        logger.info(
            "RAG retriever initialized: %d vectors, hybrid retrieval=[%s], workspace=%s",
            indexer.total_vectors,
            "+".join(components) if components else "FAISS-only",
            workspace_root,
        )
        return self._rag_retriever

    async def query(self, user_input: str, session_id: str = "default") -> dict:
        """Process a user query and return the result.

        P0-1 fix: use TriggerFlow orchestration instead of directly calling run_pipeline.
        P1-1 fix: concurrency control is managed by the Agently native scheduler + TriggerFlow execution concurrency.
        request_timeout is kept as a business-layer timeout guard.
        """
        from src.agent.flow import run_flow

        return await run_flow(
            user_input=user_input,
            session_id=session_id,
            chat_agent=self.chat_agent,
            session_registry=self.session_registry,
            rag_retriever=self._rag_retriever,
            query_rewriter=getattr(self, "_query_rewriter", None),
            reasoning_agent=getattr(self, "_reasoning_agent", None),
            embedding_agent=self.embedding_agent,
            memory_store=getattr(self, "_memory_store", None),
            request_timeout=self._request_timeout,
        )


async def interactive_mode(agent: InsuranceAgent) -> None:
    """Interactive CLI mode."""
    # Input sanitization function: remove surrogate chars
    def _clean(text: str) -> str:
        return text.encode("utf-8", errors="replace").decode("utf-8")

    print("=" * 60)
    print("Insurance RAG Agent (type 'quit' to exit)")
    print("=" * 60)

    session_id = "cli-session-001"

    while True:
        try:
            user_input = _clean(input("\nYou: ").strip())
            if not user_input or user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            result = await agent.query(user_input, session_id=session_id)

            print(f"\nAssistant: {result.get('answer', 'No answer')}")

            # Display source details (number + document title + original snippet)
            source_details = result.get("source_details")
            if source_details:
                print("\nCitation sources:")
                for sd in source_details:
                    print(f"  [{sd['num']}] {sd['title']}")
                    snippet = sd.get("snippet", "")
                    if snippet:
                        # Display the original snippet, each line indented for alignment
                        print(f"      {snippet}")
            elif result.get("sources"):
                # Fallback: show raw sources when source_details is absent
                print(f"Sources: {', '.join(result['sources'])}")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            logger.error("query failed: %s", e)
            print(f"\nError: {e}")


async def main() -> None:
    """Main entrypoint."""
    agent = InsuranceAgent()

    try:
        agent.init_rag()
    except FileNotFoundError as e:
        logger.warning("RAG not initialized: %s", e)
        print(f"Notice: {e}")
        print("Will run in pure LLM mode (no RAG retrieval)\n")

    await interactive_mode(agent)


if __name__ == "__main__":
    asyncio.run(main())