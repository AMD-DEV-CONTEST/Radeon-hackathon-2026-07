"""
RAG Engine — 基于 LlamaIndex 的本地知识检索引擎。
支持文档加载、向量索引、语义检索，运行在 AMD GPU 上。
"""

from pathlib import Path
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding


class RAGEngine:
    def __init__(self, config: dict):
        self.config = config
        self._init_embedding()
        self.index = None
        self._build_index()

    def _init_embedding(self):
        """初始化嵌入模型（运行在 AMD GPU 上）。"""
        embed_model_name = self.config["rag"]["embedding_model"]
        Settings.embed_model = HuggingFaceEmbedding(model_name=embed_model_name)
        Settings.chunk_size = self.config["rag"]["chunk_size"]
        Settings.chunk_overlap = self.config["rag"]["chunk_overlap"]

    def _build_index(self):
        """从 data/ 目录构建向量索引。"""
        data_dir = Path(__file__).parent.parent / "data" / "sample_docs"
        if data_dir.exists() and list(data_dir.glob("*")):
            documents = SimpleDirectoryReader(str(data_dir)).load_data()
            self.index = VectorStoreIndex.from_documents(documents)

    def retrieve(self, query: str) -> str:
        """检索与查询相关的知识库内容。"""
        if self.index is None:
            return ""

        query_engine = self.index.as_query_engine(
            similarity_top_k=self.config["rag"]["top_k"]
        )
        response = query_engine.query(query)
        return str(response)

    def add_documents(self, file_paths: list[str]):
        """动态添加新文档到索引。"""
        from llama_index.core import Document

        docs = []
        for fp in file_paths:
            path = Path(fp)
            if path.exists():
                text = path.read_text(encoding="utf-8")
                docs.append(Document(text=text, metadata={"source": str(path)}))

        if docs:
            if self.index is None:
                self.index = VectorStoreIndex.from_documents(docs)
            else:
                for doc in docs:
                    self.index.insert(doc)
