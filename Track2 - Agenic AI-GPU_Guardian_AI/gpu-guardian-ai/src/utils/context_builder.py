"""
context_builder.py

Builds a context-specific report for the LLM
based on the user's question category.
"""


def build_context(system_report, question_category):
    """
    Returns only the relevant portion of the
    System Health Report for the LLM.
    """

    category = question_category.lower()

    if category == "gpu":
        gpu = extract_section(
            system_report,
            [
                "GPU",
            ]
        )

        diagnosis = extract_diagnosis(
            system_report,
            "gpu"
        )

        recommendations = extract_section(
            system_report,
            [
                "PRIORITIZED RECOMMENDATIONS",
            ]
        )

        return "\n\n".join([
            gpu,
            diagnosis,
            recommendations,
    ])

    elif category == "cpu":
        cpu = extract_section(system_report, ["CPU INFORMATION"])

        diagnosis = extract_diagnosis(system_report, "cpu")

        recommendations = extract_section(
            system_report,
            ["PRIORITIZED RECOMMENDATIONS"]
        )

        return "\n\n".join([
            cpu,
            diagnosis,
            recommendations,
    ])
    elif category == "memory":
        memory = extract_section(system_report, ["MEMORY INFORMATION"])

        diagnosis = extract_diagnosis(system_report, "memory")

        recommendations = extract_section(
            system_report,
            ["PRIORITIZED RECOMMENDATIONS"]
        )

        return "\n\n".join([
            memory,
            diagnosis,
            recommendations,
    ])
    elif category == "disk":
        disk = extract_section(system_report, ["DISK INFORMATION"])

        diagnosis = extract_diagnosis(system_report, "disk")

        recommendations = extract_section(
            system_report,
            ["PRIORITIZED RECOMMENDATIONS"]
        )

        return "\n\n".join([
            disk,
            diagnosis,
            recommendations,
    ])
    elif category == "network":
        network = extract_section(system_report, ["NETWORK INFORMATION"])

        diagnosis = extract_diagnosis(system_report, "network")

        recommendations = extract_section(
            system_report,
            ["PRIORITIZED RECOMMENDATIONS"]
        )

        return "\n\n".join([
            network,
            diagnosis,
            recommendations,
    ])
    elif category == "rocm":
        diagnosis = extract_diagnosis(
            system_report,
            "rocm"
        )

        return diagnosis

    elif category.lower() == "overall":

        overall = extract_section(
            system_report,
            [
                "OVERALL SYSTEM HEALTH",
                "KEY INSIGHTS",
            ]
        )

        diagnosis = extract_diagnosis(
            system_report,
            "overall"
        )

        recommendations = extract_section(
            system_report,
            [
                "PRIORITIZED RECOMMENDATIONS",
            ]
        )

        return "\n\n".join([
            overall,
            diagnosis,
            recommendations,
        ])

    elif category == "diagnosis":
        return extract_section(
            system_report,
            [
                "INTELLIGENT DIAGNOSIS",
            ]
        )
    elif category == "recommendations":
        return extract_section(
            system_report,
            [
                "PRIORITIZED RECOMMENDATIONS",
            ]
        )

    else:
        return system_report

def extract_section(report, section_names):
    """
    Extract complete report sections.
    """

    headers = [
        "GPU ==========================",
        "CPU INFORMATION",
        "MEMORY INFORMATION",
        "DISK INFORMATION",
        "NETWORK INFORMATION",
        "OVERALL SYSTEM HEALTH",
        "KEY INSIGHTS",
        "INTELLIGENT DIAGNOSIS",
        "PRIORITIZED RECOMMENDATIONS",
    ]

    extracted = []

    for target in section_names:

        target = target.upper()

        start = None

        # Find section start
        for header in headers:
            if target in header.upper():

                if header in report:
                    start = report.index(header)
                    current_header = header
                    break

        if start is None:
            continue

        end = len(report)

        # Find next header
        current_index = headers.index(current_header)

        for next_header in headers[current_index + 1:]:

            pos = report.find(next_header, start + len(current_header))

            if pos != -1:
                end = pos
                break

        extracted.append(report[start:end].strip())

    if extracted:
        return "\n\n".join(extracted)

    return report

def extract_diagnosis(report, category):
    """
    Return only diagnosis blocks matching the requested category.
    """

    start = report.find("INTELLIGENT DIAGNOSIS")

    end = report.find("PRIORITIZED RECOMMENDATIONS")

    if start == -1 or end == -1:
        return ""

    diagnosis = report[start:end]

    if category == "overall":
        return diagnosis

    allowed = {
        "gpu": ["GPU", "ROCM"],
        "cpu": ["CPU"],
        "memory": ["MEMORY"],
        "disk": ["DISK"],
        "network": ["NETWORK"],
        "rocm": ["ROCM"],
        "system": ["SYSTEM"],
        "overall": [],
    }
    wanted = allowed.get(category.lower(), [])

    blocks = diagnosis.split("--------------------------------------------------")

    result = [
        "INTELLIGENT DIAGNOSIS\n=================================================="
    ]

    for block in blocks:

        upper = block.upper()

        for item in wanted:

            if f"CATEGORY        : {item}" in upper:

                result.append("--------------------------------------------------")
                result.append(block.strip())
                break

    return "\n".join(result)
