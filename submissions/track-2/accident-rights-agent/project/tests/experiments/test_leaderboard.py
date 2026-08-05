from __future__ import annotations

from experiments.sparse_feedback.leaderboard import generate_leaderboard


def test_leaderboard_is_ranked_and_written(tmp_path):
    rag = {
        "configurations": [
            {
                "configuration": "top4-rerank3",
                "retrieval_top_k": 4,
                "rerank_keep": 3,
                "citation_accuracy": 0.8,
                "final_verifier_score": 80,
                "latency_seconds": 0.1,
                "token_usage": 100,
            },
            {
                "configuration": "top8-rerank5",
                "retrieval_top_k": 8,
                "rerank_keep": 5,
                "citation_accuracy": 0.9,
                "final_verifier_score": 90,
                "latency_seconds": 0.2,
                "token_usage": 150,
            },
        ]
    }
    prompt = {
        "prompts": [
            {
                "prompt_id": "A",
                "correctness": 0.7,
                "evidence_grounding": 0.7,
                "legal_citation": 0.7,
                "verifier_pass_rate": 0.5,
                "latency_seconds": 1.0,
                "input_tokens": 500,
                "output_tokens": 100,
            },
            {
                "prompt_id": "B",
                "correctness": 0.9,
                "evidence_grounding": 0.9,
                "legal_citation": 0.9,
                "verifier_pass_rate": 1.0,
                "latency_seconds": 1.1,
                "input_tokens": 550,
                "output_tokens": 120,
            },
        ]
    }
    rows = generate_leaderboard(tmp_path, rag_result=rag, prompt_result=prompt)
    assert len(rows) == 4
    assert [row["rank"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["composite_score"] >= rows[-1]["composite_score"]
    assert (tmp_path / "leaderboard.csv").exists()
