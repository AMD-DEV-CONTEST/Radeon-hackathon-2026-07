"""Rebuild sqlite-vec data from authoritative entity rows."""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.embedding import create_embedding_provider
from services.vector_store import VectorStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the local BGE-M3 vector index")
    parser.add_argument("command", choices=("status", "rebuild"))
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--book-id")
    args = parser.parse_args()

    provider = create_embedding_provider(model_root=args.model_root)
    if not provider.status().available:
        print(json.dumps({"error": provider.status().detail}, indent=2))
        return 2
    store = VectorStore(args.db_path.resolve(), provider)
    store.init_db()
    result = store.index_status() if args.command == "status" else store.rebuild_from_entities(args.book_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
