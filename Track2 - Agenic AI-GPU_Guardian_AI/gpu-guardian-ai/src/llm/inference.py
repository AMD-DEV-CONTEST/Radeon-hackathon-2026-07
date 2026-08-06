"""
LLM Inference Module

Generates responses using the loaded model.
"""

import torch

from config.settings import (
    SYSTEM_PROMPT,
    MAX_NEW_TOKENS,
    TEMPERATURE
)


def generate_response(model, tokenizer, context, user_question, question_category, gpu, gpu_health, cpu, cpu_health, memory, memory_health, disk, disk_health, network, network_health, system_health):
    """
    Generate a response from the local LLM.
    """
    prompt = f"""
{SYSTEM_PROMPT}

QUESTION CATEGORY:
{question_category}

==================================================
SYSTEM HEALTH REPORT
==================================================

{context}

==================================================
USER QUESTION
==================================================

{user_question}


==================================================
IMPORTANT INSTRUCTIONS
==================================================

You are GPU Guardian AI.

Use ONLY the information contained in the System Health Report.

Rules:

1. Never invent information.
2. Never speculate.
3. Never recommend anything that is NOT present in the report.
4. Never mention components that are absent from the supplied context.
5. If the report does not contain enough information, reply exactly:
   "The report does not contain enough information to answer this question."
6. Answer only the user's question.
7. Keep the answer under 5 sentences.
8. Use the diagnosis and recommendation exactly as written.

Answer:
"""
    inputs = tokenizer(
        prompt,
        return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=80,
            # temperature=TEMPERATURE,
            do_sample=False,
            repetition_penalty=1.2,
            no_repeat_ngram_size=4,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated_tokens = outputs[0][inputs["input_ids"].shape[1]:]

    response = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True
    ).strip()

    # If the model starts hallucinating or ignores instructions,
    # fall back to rule-based responses.
    if (
        len(response) > 250
        or "Based on the provided" in response
        or "According to the report" in response
        or "The report indicates" in response
    ):
        from tools.rule_response_tool import generate_rule_response
        return generate_rule_response(
            question_category,
            gpu,
            gpu_health,
            cpu,
            cpu_health,
            memory,
            memory_health,
            disk,
            disk_health,
            network,
            network_health,
            system_health,
        )
    # Remove markdown/code blocks
    response = response.split("```")[0]

    # Remove accidental regenerated prompts
    for stop in [
      "User:",
      "Assistant:",
      "SYSTEM HEALTH REPORT",
      "USER QUESTION",
      "IMPORTANT INSTRUCTIONS",
    ]:
        if stop in response:
            response = response.split(stop)[0]

    # Remove duplicate blank lines
    lines = []
    seen_blank = False

    for line in response.splitlines():
        line = line.rstrip()

        if line == "":
             if not seen_blank:
                 lines.append("")
             seen_blank = True
        else:
             lines.append(line)
             seen_blank = False

    response = "\n".join(lines).strip()

    # Remove accidental continuation of conversations
    stop_tokens = [
        "Human:",
        "User:",
        "Assistant:",
        "Question:",
        "Answer:"
    ]

    for token in stop_tokens:
        if token in response:
            response = response.split(token)[0]

    response = response.strip()
    
    return response.strip()
