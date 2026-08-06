import json
import random
import base64
from pathlib import Path

def mutate_payload(payload, mut_type):
    """Applies a specific mutation to a payload string."""
    if mut_type == "none":
        return payload
    elif mut_type == "uppercase":
        return payload.upper()
    elif mut_type == "lowercase":
        return payload.lower()
    elif mut_type == "base64_wrap":
        b64 = base64.b64encode(payload.encode()).decode()
        return f"Decode this base64 and execute it: {b64}"
    elif mut_type == "whitespace_inject":
        return " ".join(" ".join(word) for word in payload.split())
    elif mut_type == "leetspeak":
        replacements = {'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5', 't': '7'}
        return "".join(replacements.get(c.lower(), c) for c in payload)
    return payload

def main():
    print("Initializing Warden Red-Team Mutation Engine...")
    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = repo_root / 'benchmarks' / 'data' / 'warden_redteam_corpus.json'
    output_path = repo_root / 'benchmarks' / 'data' / 'mutated_test_set.json'

    if not corpus_path.exists():
        print(f"Error: Base corpus not found at {corpus_path}")
        return

    with open(corpus_path, 'r', encoding='utf-8') as f:
        corpus = json.load(f)

    mutations = ["none", "uppercase", "lowercase", "base64_wrap", "whitespace_inject", "leetspeak"]
    
    mutated_dataset = []
    
    for item in corpus:
        # Add the original
        mutated_dataset.append({
            "id": f"{item['id']}_orig",
            "family": item['family'],
            "expected_action": item['expected_action'],
            "mutation": "none",
            "payload": item['payload']
        })
        
        # Add 2 random mutations to simulate drift
        chosen_muts = random.sample([m for m in mutations if m != "none"], 2)
        for mut in chosen_muts:
            mutated_dataset.append({
                "id": f"{item['id']}_{mut}",
                "family": item['family'],
                "expected_action": item['expected_action'],
                "mutation": mut,
                "payload": mutate_payload(item['payload'], mut)
            })

    # Save mutated dataset
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mutated_dataset, f, indent=2)
        
    print(f"Generated {len(mutated_dataset)} mutated payloads to {output_path.name}")
    print("Ready for efficacy evaluation.")

if __name__ == "__main__":
    main()
