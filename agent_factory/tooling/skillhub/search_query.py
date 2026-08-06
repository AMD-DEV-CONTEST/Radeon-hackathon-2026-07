from __future__ import annotations


SKILLHUB_SEARCH_QUERY_MIN_KEYWORDS = 1
SKILLHUB_SEARCH_QUERY_MAX_KEYWORDS = 3
SKILLHUB_SEARCH_QUERY_MAX_CHARS = 96
SKILLHUB_SEARCH_KEYWORD_MAX_CHARS = 32
SKILLHUB_SEARCH_QUERY_PATTERN = (
    rf"^\S{{1,{SKILLHUB_SEARCH_KEYWORD_MAX_CHARS}}}"
    rf"(?:\s+\S{{1,{SKILLHUB_SEARCH_KEYWORD_MAX_CHARS}}})"
    rf"{{0,{SKILLHUB_SEARCH_QUERY_MAX_KEYWORDS - 1}}}$"
)


def normalize_skillhub_search_query(query: str) -> str:
    keywords = str(query or "").strip().split()
    if not (SKILLHUB_SEARCH_QUERY_MIN_KEYWORDS <= len(keywords) <= SKILLHUB_SEARCH_QUERY_MAX_KEYWORDS):
        raise ValueError(
            "SkillHUB search query must contain 1 to 3 short keywords. "
            "Do not pass long requirement text or a pile of mixed synonyms; split broad discovery into multiple search calls."
        )
    oversized = [keyword for keyword in keywords if len(keyword) > SKILLHUB_SEARCH_KEYWORD_MAX_CHARS]
    if oversized:
        raise ValueError(
            f"SkillHUB search keyword is too long: {oversized[0]!r}. "
            f"Each keyword must be at most {SKILLHUB_SEARCH_KEYWORD_MAX_CHARS} characters."
        )
    normalized = " ".join(keywords)
    if len(normalized) > SKILLHUB_SEARCH_QUERY_MAX_CHARS:
        raise ValueError(
            f"SkillHUB search query must be at most {SKILLHUB_SEARCH_QUERY_MAX_CHARS} characters."
        )
    return normalized
