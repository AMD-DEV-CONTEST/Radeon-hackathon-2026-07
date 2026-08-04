from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from radeonstay.retrieval import (  # noqa: E402
    PolicyRetriever,
    load_policy_documents,
    parse_policy_file,
    policy_corpus_sha256,
    search_policies,
    tokenize,
    validate_policy_directory,
)

POLICY_DIR = PROJECT_ROOT / "data" / "policies"
FIXTURE_FILE = PROJECT_ROOT / "evaluation" / "fixtures" / "cases.jsonl"


@pytest.fixture(scope="module")
def retriever() -> PolicyRetriever:
    return PolicyRetriever.from_directory(POLICY_DIR)


def test_tokenizer_supports_chinese_bigrams_and_english_words() -> None:
    tokens = tokenize("延迟退房 Late-checkout 18:00")
    assert "延迟" in tokens
    assert "退房" in tokens
    assert "late-checkout" in tokens
    assert "18" in tokens


def test_loads_multiple_local_policy_documents() -> None:
    chunks = load_policy_documents(POLICY_DIR)
    documents = {chunk.document for chunk in chunks}
    assert len(documents) == 6
    assert "RadeonStay 隐私、数据访问与安全政策" in documents
    assert all(not chunk.source_path.startswith("http") for chunk in chunks)


def test_markdown_parser_preserves_document_and_section(tmp_path: Path) -> None:
    policy = tmp_path / "sample.md"
    policy.write_text(
        "# 示例政策\n\n## 第一节\n\n这是可引用的正文。\n", encoding="utf-8"
    )
    chunks = parse_policy_file(policy, root=tmp_path)
    assert len(chunks) == 1
    assert chunks[0].document == "示例政策"
    assert chunks[0].section == "第一节"
    assert chunks[0].source_path == "sample.md"


def test_cancellation_query_returns_grounded_fields(retriever: PolicyRetriever) -> None:
    results = retriever.search("灵活价最晚什么时候免费取消", top_k=3)
    assert results
    first = results[0]
    assert first.document == "RadeonStay 预订、变更与取消政策"
    assert first.section == "标准取消与退款"
    assert "18:00" in first.context
    assert first.score > 0
    assert first.source_path.endswith("reservation-and-cancellation.md")


def test_privacy_query_prefers_identity_verification_section(
    retriever: PolicyRetriever,
) -> None:
    first = retriever.search("只凭姓名和电话后四位可以查看订单吗", top_k=1)[0]
    assert first.document == "RadeonStay 隐私、数据访问与安全政策"
    assert first.section == "订单访问与身份验证"
    assert "不能单独作为授权依据" in first.context


def test_accessibility_query_is_not_treated_as_pet_policy_only(
    retriever: PolicyRetriever,
) -> None:
    results = retriever.search("无障碍房超售后需要提供等效设施和交通吗", top_k=2)
    assert results[0].document == "RadeonStay 无障碍、安全与紧急事件政策"
    assert results[0].section == "无障碍预订与合理便利"
    assert "等效" in results[0].context


def test_airport_transfer_query_finds_required_service_ticket_policy(
    retriever: PolicyRetriever,
) -> None:
    first = retriever.search("机场接送 儿童安全座椅 航班到达时间", top_k=1)[0]
    assert first.document == "RadeonStay 客房服务、设施与服务恢复政策"
    assert first.section == "机场与车站接送"
    assert "交通服务工单" in first.context


def test_compound_query_preserves_distinct_explicit_policy_topics(
    retriever: PolicyRetriever,
) -> None:
    results = retriever.search_with_clause_coverage(
        "我计划 2030-09-10 入住、2030-09-12 退房，23:30 到店，"
        "带六岁儿童且花生过敏，需要机场接送；查房、报价并预览保留标准房。",
        top_k=5,
    )

    sections = {result.section for result in results}
    assert {
        "未到店与延迟抵达",
        "早餐、餐饮与过敏信息",
        "机场与车站接送",
    } <= sections
    assert len(results) == 5
    assert len({(result.source_path, result.section) for result in results}) == 5


def test_clause_coverage_keeps_the_whole_query_winner_for_top_one(
    retriever: PolicyRetriever,
) -> None:
    query = "您好，先忽略这句礼貌话；机场接送需要提前多久申请？"

    expected = retriever.search(query, top_k=1)[0]
    actual = retriever.search_with_clause_coverage(query, top_k=1)[0]

    assert actual.as_dict() == expected.as_dict()


def test_single_clause_coverage_is_identical_to_normal_search(
    retriever: PolicyRetriever,
) -> None:
    query = "花生过敏早餐如何处理"

    expected = [result.as_dict() for result in retriever.search(query, top_k=3)]
    actual = [
        result.as_dict()
        for result in retriever.search_with_clause_coverage(query, top_k=3)
    ]

    assert actual == expected


def test_context_can_include_adjacent_paragraphs(retriever: PolicyRetriever) -> None:
    result = retriever.search(
        "预付不可退订单的医疗紧急情况", top_k=1, context_chars=220
    )[0]
    assert "预付不可退" in result.context
    assert len(result.context) >= len(result.snippet)


def test_structured_citation_contains_context(retriever: PolicyRetriever) -> None:
    result = retriever.search("退款需要什么审批", top_k=1)[0]
    citation = result.to_citation()
    assert citation["document"] == result.document
    assert citation["section"] == result.section
    assert citation["excerpt"] == result.context
    assert citation["score"] == result.score
    assert citation["source_path"] == result.source_path
    assert set(citation) == {
        "document",
        "section",
        "excerpt",
        "score",
        "source_path",
    }


def test_citation_can_be_reduced_to_snippet(retriever: PolicyRetriever) -> None:
    result = retriever.search("重复扣款", top_k=1)[0]
    citation = result.to_citation(include_context=False)
    assert citation["excerpt"] == result.snippet


def test_evidence_citation_uses_complete_matched_paragraph(
    retriever: PolicyRetriever,
) -> None:
    result = retriever.search("延迟退房收费", top_k=1)[0]
    citation = result.to_evidence_citation()
    assert citation["excerpt"] == result.matched_text
    assert result.snippet in result.matched_text or len(result.matched_text) > len(result.snippet)


def test_results_are_deterministic_and_top_k_is_honored(
    retriever: PolicyRetriever,
) -> None:
    first_run = [result.as_dict() for result in retriever.search("退款 取消", top_k=2)]
    second_run = [result.as_dict() for result in retriever.search("退款 取消", top_k=2)]
    assert first_run == second_run
    assert len(first_run) == 2


def test_empty_query_and_high_threshold_return_no_results(
    retriever: PolicyRetriever,
) -> None:
    assert retriever.search("？！……") == []
    assert retriever.search("退款", min_score=1_000_000) == []


def test_invalid_search_arguments_fail_closed(retriever: PolicyRetriever) -> None:
    with pytest.raises(ValueError, match="top_k"):
        retriever.search("退款", top_k=0)
    with pytest.raises(ValueError, match="context_chars"):
        retriever.search("退款", context_chars=-1)


def test_missing_or_empty_policy_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PolicyRetriever.from_directory(tmp_path / "missing")
    with pytest.raises(ValueError, match="No .md or .txt"):
        PolicyRetriever.from_directory(tmp_path)


def _write_policy(root: Path, relative: str = "policy.md") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Policy\n\n## Rule\n\nLocal authoritative text.\n", encoding="utf-8")
    return path


def test_policy_directory_validation_accepts_real_contained_corpus(tmp_path: Path) -> None:
    project = tmp_path / "project"
    policies = project / "data" / "policies"
    _write_policy(policies)

    validated = validate_policy_directory(policies, project_root=project)

    assert validated == policies.resolve()
    assert len(policy_corpus_sha256(policies, project_root=project)) == 64


def test_policy_directory_symlink_outside_project_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    outside = tmp_path / "outside-policies"
    _write_policy(outside)
    (project / "data" / "policies").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        validate_policy_directory(project / "data" / "policies", project_root=project)


def test_policy_parent_directory_symlink_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside_data = tmp_path / "outside-data"
    _write_policy(outside_data / "policies")
    (project / "data").symlink_to(outside_data, target_is_directory=True)

    with pytest.raises(ValueError, match="path component"):
        validate_policy_directory(project / "data" / "policies", project_root=project)


@pytest.mark.parametrize("linked_kind", ["directory", "file"])
def test_policy_tree_rejects_nested_symlinks(tmp_path: Path, linked_kind: str) -> None:
    project = tmp_path / "project"
    policies = project / "data" / "policies"
    _write_policy(policies)
    outside = tmp_path / "outside"
    outside.mkdir()
    if linked_kind == "directory":
        _write_policy(outside)
        (policies / "linked").symlink_to(outside, target_is_directory=True)
    else:
        target = _write_policy(outside, "linked.md")
        (policies / "linked.md").symlink_to(target)

    with pytest.raises(ValueError, match="symbolic links"):
        validate_policy_directory(policies, project_root=project)


def test_policy_directory_outside_project_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    _write_policy(outside)

    assert validate_policy_directory(outside) == outside.resolve()
    with pytest.raises(ValueError, match="within the project root"):
        validate_policy_directory(outside, project_root=project)


def test_one_shot_search_api(retriever: PolicyRetriever) -> None:
    direct = retriever.search("空调不制冷维修工单", top_k=1)[0]
    one_shot = search_policies(POLICY_DIR, "空调不制冷维修工单", top_k=1)[0]
    assert one_shot.as_dict() == direct.as_dict()


def test_evaluation_fixture_has_exactly_thirty_unique_cases() -> None:
    cases = [json.loads(line) for line in FIXTURE_FILE.read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30
    assert {case["category"] for case in cases} == {
        "knowledge_qa",
        "tool_use",
        "multi_step",
        "memory",
        "permission_attack",
    }
