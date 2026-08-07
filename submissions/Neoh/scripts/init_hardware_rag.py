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

# 硬件研发知识库默认目录：把芯片 Datasheet / Reference Manual / Errata /
# 应用笔记 / 常用 MCU 手册 放进这里，运行本脚本即可建库
DEFAULT_HARDWARE_DOCS_DIR = "./data/hardware_documents"


def main():
    parser = argparse.ArgumentParser(description="初始化硬件研发知识库（RAG）")
    parser.add_argument(
        "--docs-dir",
        type=str,
        default=DEFAULT_HARDWARE_DOCS_DIR,
        help="硬件文档目录（默认 ./data/hardware_documents）",
    )
    parser.add_argument(
        "--index-path",
        type=str,
        default="./data/faiss_index",
        help="FAISS 索引保存路径（与 agent 默认路径一致，硬件文档会合并进主索引并带 domain=hardware 标签）",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="all-MiniLM-L6-v2",
        help="Embedding 模型名称",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="文本分块大小",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="分块重叠大小",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="清空现有硬件索引后重建",
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
            logger.info("清空现有硬件索引...")
            memory_manager.clear_long_term_memory()

        if not os.path.exists(args.docs_dir):
            logger.warning(f"硬件文档目录不存在: {args.docs_dir}")
            os.makedirs(args.docs_dir, exist_ok=True)
            logger.info("已为你创建该目录，请将芯片手册 / Datasheet 放入后重新运行：")
            logger.info(f"  {os.path.abspath(args.docs_dir)}")
            sys.exit(0)

        supported_extensions = [".pdf", ".docx", ".md", ".txt"]
        file_paths = []
        for filename in sorted(os.listdir(args.docs_dir)):
            _, ext = os.path.splitext(filename)
            if ext.lower() in supported_extensions:
                file_paths.append(os.path.join(args.docs_dir, filename))

        if not file_paths:
            logger.warning(f"未找到支持的硬件文档: {args.docs_dir}")
            logger.info("支持的格式: PDF, DOCX, MD, TXT")
            logger.info("请放入芯片 Datasheet / Reference Manual / Errata 后重新运行")
            sys.exit(0)

        logger.info(f"发现 {len(file_paths)} 个硬件文档：")
        for fp in file_paths:
            logger.info(f"  - {os.path.basename(fp)}")

        logger.info("开始处理硬件文档...")
        total_chunks = memory_manager.add_documents(
            file_paths, metadata_extra={"domain": "hardware"}
        )

        logger.info("硬件研发知识库初始化完成！")
        logger.info(f"共处理 {len(file_paths)} 个文档，生成 {total_chunks} 个文本块")
        logger.info(f"索引保存在: {args.index_path}")
        if total_chunks == 0:
            logger.warning("未生成任何文本块，请检查文档是否为空或格式受支持")

    except Exception as e:
        logger.error(f"硬件知识库初始化失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
