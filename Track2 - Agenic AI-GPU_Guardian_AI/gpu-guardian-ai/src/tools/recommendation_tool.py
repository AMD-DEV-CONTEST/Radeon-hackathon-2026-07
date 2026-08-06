"""
recommendation_tool.py

Generates prioritized recommendations from diagnosis.
"""


def generate_recommendations(diagnosis):
    """
    Build a prioritized recommendation list.
    """

    recommendations = []

    severity_order = {
        "Critical": 0,
        "Warning": 1,
        "Info": 2
    }

    # Sort diagnosis by severity
    diagnosis = sorted(
        diagnosis,
        key=lambda item: severity_order.get(
            item.get("severity", "Info"),
            99
        )
    )

    seen = set()

    for item in diagnosis:

        recommendation = item.get("recommendation", "").strip()

        if (
            recommendation
            and recommendation not in seen
        ):
            recommendations.append({
                "severity": item.get("severity"),
                "category": item.get("category"),
                "recommendation": recommendation
            })
            seen.add(recommendation)

    critical = [
        r for r in recommendations
        if r["severity"] == "Critical"
    ]

    warning = [
        r for r in recommendations
        if r["severity"] == "Warning"
    ]

    info = [
        r for r in recommendations
        if r["severity"] == "Info"
    ]

    return critical + warning + info
