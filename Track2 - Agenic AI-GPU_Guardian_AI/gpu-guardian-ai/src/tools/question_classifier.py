"""
question_classifier.py

Classifies user questions to provide focused context to the LLM.
"""


def classify_question(question):
    """
    Returns the primary category for the user's question.
    """

    question = question.lower()

    if any(word in question for word in [
        "gpu",
        "vram",
        "rocm",
        "graphics",
        "temperature",
        "power"
    ]):
        return "GPU"

    if any(word in question for word in [
        "cpu",
        "processor",
        "core",
        "load"
    ]):
        return "CPU"

    if any(word in question for word in [
        "memory",
        "ram"
    ]):
        return "Memory"

    if any(word in question for word in [
        "disk",
        "storage",
        "filesystem"
    ]):
        return "Disk"

    if any(word in question for word in [
        "network",
        "latency",
        "packet",
        "bandwidth"
    ]):
        return "Network"

    if any(word in question for word in [
        "recommend",
        "recommendation",
        "advice",
        "suggest"
    ]):
        return "Recommendation"

    if any(word in question for word in [
        "bottleneck",
        "diagnosis",
        "issue",
        "problem",
        "health",
        "overall"
    ]):
        return "Diagnosis"

    return "General"
