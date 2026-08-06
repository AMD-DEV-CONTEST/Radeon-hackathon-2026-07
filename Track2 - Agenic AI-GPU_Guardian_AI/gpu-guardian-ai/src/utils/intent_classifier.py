"""
Intent Classifier

Determines which part of the report should be sent to the LLM.
"""

def classify_intent(question: str) -> str:
    """
    Return the user's primary intent.
    """

    q = question.lower()

    if any(word in q for word in [
        "overall",
        "entire system",
        "system health",
        "health summary",
        "summarize",
        "summary"
    ]):
        return "overall"

    if any(word in q for word in [
        "recommend",
        "recommendation",
        "recommendations",
        "suggest",
        "suggestion",
        "what should i do",
        "next step",
        "action",
        "fix",
        "resolve",
    ]):
        return "recommendations"

    if any(word in q for word in [
        "diagnosis",
        "root cause",
        "issue",
        "problem",
        "finding",
        "bottleneck"
    ]):
        return "diagnosis"

    if any(word in q for word in [
        "gpu",
        "graphics",
        "vram",
        "video memory",
        "edge temperature",
        "junction temperature",
        "gpu usage",
        "gpu idle",
        "power consumption",
        "power draw",
    ]):
        return "gpu"

    if any(word in q for word in [
        "cpu",
        "processor",
        "core",
        "cores",
        "logical core",
        "physical core",
        "cpu usage",
        "load average",
        "frequency",
        "clock speed",
    ]):
        return "cpu"
    
    if any(word in q for word in [
        "memory",
        "ram",
        "swap",
        "available memory",
        "used memory",
        "memory usage",
        "free memory",
    ]):
        return "memory"

    if any(word in q for word in [
        "disk",
        "storage",
        "ssd",
        "hdd",
        "filesystem",
        "disk usage",
        "free space",
        "storage usage",
    ]):
        return "disk"

    if any(word in q for word in [
        "network",
        "internet",
        "packet",
        "latency",
        "bandwidth",
        "drops",
        "packet loss",
        "errors",
        "connection",
        "ethernet",
    ]):
        return "network"
    
    if any(word in q for word in [
        "rocm",
        "amd",
        "radeon",
        "hip",
        "gpu runtime",
        "gpu driver",
    ]):
        return "rocm"
    return "overall"
