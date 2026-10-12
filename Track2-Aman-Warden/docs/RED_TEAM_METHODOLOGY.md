# Warden Red-Team Methodology

To mathematically prove the security efficacy of the Warden 3-Tier Router, we utilize a rigorous, standardized red-team evaluation harness. This ensures Warden not only operates with ultra-low latency, but successfully intercepts zero-day and obfuscated attacks with high Precision and Recall.

## 1. Attack Taxonomy
The base corpus (`benchmarks/data/warden_redteam_corpus.json`) is designed around a 10-family taxonomy, mirroring standards set by Lakera and Protect AI:

1. **Direct Injection**: Blatant prompt overrides ("Ignore previous instructions").
2. **Roleplay / DAN**: Semantic deception asking the model to assume an unrestricted persona.
3. **Base64 Obfuscation**: Encoding malicious payloads to bypass naive regex.
4. **Payload Splitting**: Chunking malicious words to evade static detection.
5. **Multilingual Evasion**: Translating attacks into non-English languages.
6. **PII Exfiltration**: Attempting to extract SSNs, passwords, or emails from context.
7. **SQL Injection (SQLi)**: Classic database exploits mapped to LLM interfaces.
8. **Cross-Site Scripting (XSS)**: Payload generation for downstream web exploitation.
9. **Tone Transfer**: Semantic attacks altering the required output tone (e.g., "Hacker voice").
10. **Benign (Control)**: Standard, safe user requests to test for False Positives.

## 2. The Mutator Engine
Zero-day attacks rarely mirror static datasets perfectly. To simulate real-world "drift," Warden employs a programmatic **Mutator Engine** (`benchmarks/redteam_mutator.py`). 

Before every evaluation run, the engine generates dynamic variants of the base corpus using permutations such as:
- **Whitespace Injection**
- **Leetspeak Translation**
- **Base64 Wrapping**
- **Case Evasion**

## 3. Evaluation Harness
The `benchmarks/efficacy_evaluator.py` script streams the mutated dataset through the active Warden Router.

It produces a **Confusion Matrix** and calculates the following metrics:
- **Precision**: (True Positives / (True Positives + False Positives)) - Represents the accuracy of Warden's blocking decisions.
- **Recall**: (True Positives / (True Positives + False Negatives)) - Represents the system's "catch rate" against actual threats.
- **F1 Score**: The harmonic mean of Precision and Recall.

### Running the Evaluator
To generate empirical F1 scores on your local or cloud hardware:
```bash
python benchmarks/efficacy_evaluator.py
```
*Note: Ensure all models (Tier 1 ONNX and Tier 2 GGUF) are properly loaded for maximum efficacy, otherwise the router will gracefully degrade to Tier 0.*
