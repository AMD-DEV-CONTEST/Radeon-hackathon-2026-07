from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from openalpha_sentinel.config import Settings
from openalpha_sentinel.service import OpenAlphaService


def check_card(card: dict, expected: dict) -> list[dict]:
    checks = []
    for field in ("strategy_type", "license_spdx", "cost_disclosure"):
        checks.append(
            {
                "field": field,
                "passed": card.get(field) == expected[field],
                "actual": card.get(field),
                "expected": expected[field],
            }
        )
    for field in ("markets", "timeframes", "signals"):
        required = set(expected.get(f"{field}_contains", []))
        actual = set(card.get(field, []))
        checks.append(
            {
                "field": f"{field}_contains",
                "passed": required.issubset(actual),
                "actual": sorted(actual),
                "expected": sorted(required),
            }
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the deterministic local MVP corpus")
    parser.add_argument("--expectations", type=Path, default=Path("evals/fixture_expectations.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    expected_cards = json.loads(args.expectations.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="openalpha-eval-") as directory:
        data_dir = Path(directory)
        settings = Settings(
            data_dir=data_dir,
            db_path=data_dir / "openalpha.db",
            llm_backend="heuristic",
            allowed_domains=("github.com",),
        )
        service = OpenAlphaService(settings)
        first = service.seed_demo()
        second = service.seed_demo()
        cards = {card["title"]: card for card in service.database.list_cards()}

        details = []
        for title, expected in expected_cards.items():
            card = cards.get(title)
            if not card:
                details.append({"title": title, "field": "card_exists", "passed": False})
                continue
            details.extend({"title": title, **item} for item in check_card(card, expected))
            stored = service.database.get_card(card["id"])
            details.append(
                {
                    "title": title,
                    "field": "evidence_present",
                    "passed": bool(stored and stored["evidence"]),
                    "actual": len(stored["evidence"]) if stored else 0,
                    "expected": "> 0",
                }
            )

        queries = {
            "list": "有哪些策略？",
            "cost_disclosed": "哪些策略披露了交易成本？",
            "cost_missing": "哪些策略未披露交易成本？",
            "mit_license": "哪些策略使用 MIT 许可证？",
        }
        query_results = {}
        for name, question in queries.items():
            answer = service.ask(question, session_id=f"eval-{name}")
            query_results[name] = {
                "answer": answer.answer,
                "citation_count": len(answer.citations),
                "all_citations_resolvable": all(bool(item.url) for item in answer.citations),
                "backend": answer.backend,
            }

        passed = sum(1 for item in details if item["passed"])
        payload = {
            "corpus": {
                "expected_cards": len(expected_cards),
                "actual_cards": len(cards),
                "first_created_cards": first.created_cards,
                "second_created_cards": second.created_cards,
                "second_skipped_revisions": second.skipped_revisions,
            },
            "field_checks": {
                "passed": passed,
                "total": len(details),
                "rate": passed / len(details) if details else 0,
                "details": details,
            },
            "queries": query_results,
        }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

