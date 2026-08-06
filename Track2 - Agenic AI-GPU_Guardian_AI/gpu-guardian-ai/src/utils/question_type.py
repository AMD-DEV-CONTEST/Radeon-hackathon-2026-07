"""
Determines whether the question is factual
or requires explanation.
"""


def question_type(question: str):

    q = question.lower()

    explain_words = [
        "why",
        "how",
        "explain",
        "reason",
        "cause",
        "describe",
        "analyze",
        "interpret",
    ]

    if any(word in q for word in explain_words):
        return "llm"

    return "rule"
