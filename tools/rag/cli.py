"""
CLI contract:

    python -m tools.rag.cli ingest <file_path> [--kb-id <uuid>]
    python -m tools.rag.cli query "<query_text>" --top-k 5 [--kb-id <uuid>]
    python -m tools.rag.cli list [--kb-id <uuid>]
    python -m tools.rag.cli delete <doc_id> [--kb-id <uuid>]
    python -m tools.rag.cli reindex [--kb-id <uuid>]

Exit 0 + JSON on stdout for success. Exit 1 + message on stderr for errors.
This is the tested surface Track A wraps in Python — keep it stable.
"""

import argparse
import json
import sys

from .config import CHUNK_OVERLAP, CHUNK_SIZE, DEFAULT_KB_ID, DEFAULT_TOP_K
from .ingest import delete_document, ingest_file, list_documents, reindex_all
from .retrieve import Retriever

_retriever = Retriever()  # module-level so repeated CLI-in-process calls share cache


def cmd_ingest(args: argparse.Namespace) -> None:
    try:
        result = ingest_file(
            args.file_path,
            kb_id=args.kb_id,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    _retriever.invalidate(args.kb_id)
    print(json.dumps(result))
    sys.exit(0)


def cmd_query(args: argparse.Namespace) -> None:
    try:
        results = _retriever.query(args.query_text, top_k=args.top_k, kb_id=args.kb_id)
    except Exception as e:  # noqa: BLE001 - surface any retrieval failure to the caller
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results, indent=2))
    sys.exit(0)


def cmd_list(args: argparse.Namespace) -> None:
    print(json.dumps(list_documents(kb_id=args.kb_id), indent=2))
    sys.exit(0)


def cmd_delete(args: argparse.Namespace) -> None:
    ok = delete_document(args.doc_id, kb_id=args.kb_id)
    if not ok:
        print(f"Document not found: {args.doc_id}", file=sys.stderr)
        sys.exit(1)

    _retriever.invalidate(args.kb_id)
    print(json.dumps({"deleted": True, "doc_id": args.doc_id}))
    sys.exit(0)


def cmd_reindex(args: argparse.Namespace) -> None:
    result = reindex_all(kb_id=args.kb_id, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    _retriever.invalidate(args.kb_id)
    print(json.dumps(result))
    sys.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="EduManim RAG tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a file into the knowledge base")
    p_ingest.add_argument("file_path")
    p_ingest.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p_ingest.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    p_ingest.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP)
    p_ingest.set_defaults(func=cmd_ingest)

    p_query = sub.add_parser("query", help="Query the knowledge base")
    p_query.add_argument("query_text")
    p_query.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_query.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p_query.set_defaults(func=cmd_query)

    p_list = sub.add_parser("list", help="List indexed documents")
    p_list.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p_list.set_defaults(func=cmd_list)

    p_delete = sub.add_parser("delete", help="Delete a document")
    p_delete.add_argument("doc_id")
    p_delete.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p_delete.set_defaults(func=cmd_delete)

    p_reindex = sub.add_parser("reindex", help="Reindex all documents")
    p_reindex.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p_reindex.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    p_reindex.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP)
    p_reindex.set_defaults(func=cmd_reindex)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()