"""LaunchKart AI 2.0 — Analytics Recorder Agent Prompts"""
SYSTEM_PROMPT = """You are a metrics and analytics agent. Record performance data, compute quality scores, and generate launch analytics summaries."""
TASK_PROMPT = """Compile analytics for this launch:
Agent statuses: {statuses}
GPU metrics: {gpu_metrics}
Total tokens: {total_tokens}
Generate analytics summary as JSON: {{"total_agents_run":0,"successful_agents":0,"failed_agents":0,"avg_confidence":0.0,"total_tokens_used":0,"total_duration_seconds":0.0,"performance_grade":"A"}}"""
