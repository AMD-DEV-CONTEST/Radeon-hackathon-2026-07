import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.manager import MemoryManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="初始化 RAG 系统")
    parser.add_argument(
        "--docs-dir",
        type=str,
        default="./data/documents",
        help="文档目录"
    )
    parser.add_argument(
        "--index-path",
        type=str,
        default="./data/faiss_index",
        help="FAISS 索引保存路径"
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="all-MiniLM-L6-v2",
        help="Embedding 模型名称"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="文本分块大小"
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="分块重叠大小"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="清空现有索引"
    )
    args = parser.parse_args()

    try:
        memory_manager = MemoryManager(
            index_path=args.index_path,
            embedding_model=args.embedding_model,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )

        if args.clear:
            logger.info("清空现有索引...")
            memory_manager.clear_long_term_memory()

        if not os.path.exists(args.docs_dir):
            logger.warning(f"文档目录不存在: {args.docs_dir}")
            logger.info("创建文档目录...")
            os.makedirs(args.docs_dir, exist_ok=True)
            logger.info("请将文档放入该目录后重新运行")
            sys.exit(0)

        supported_extensions = [".pdf", ".docx", ".md", ".txt"]
        file_paths = []

        for filename in os.listdir(args.docs_dir):
            _, ext = os.path.splitext(filename)
            if ext.lower() in supported_extensions:
                file_paths.append(os.path.join(args.docs_dir, filename))

        if not file_paths:
            logger.warning(f"未找到支持的文档文件: {args.docs_dir}")
            logger.info("支持的格式: PDF, DOCX, MD, TXT")
            sys.exit(0)

        logger.info(f"发现 {len(file_paths)} 个文档文件")
        for fp in file_paths:
            logger.info(f"  - {os.path.basename(fp)}")

        logger.info("开始处理文档...")
        total_chunks = memory_manager.add_documents(file_paths)

        logger.info(f"RAG 初始化完成！")
        logger.info(f"共处理 {len(file_paths)} 个文档")
        logger.info(f"共生成 {total_chunks} 个文本块")
        logger.info(f"索引保存在: {args.index_path}")

    except Exception as e:
        logger.error(f"RAG 初始化失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()