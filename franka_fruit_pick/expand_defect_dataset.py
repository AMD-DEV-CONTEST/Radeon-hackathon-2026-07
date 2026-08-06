"""Expand defect instruction dataset with diverse examples.

Generates 500+ instructions covering:
- 7 defect dimensions (15 each = 105)
- Mixed defects (2+ dimensions per instruction)
- Boundary cases (ambiguous instructions)
- Normal instruction variants (same task, different wording)
- Scene-aware instructions (references to specific objects)

Usage:
    python expand_defect_dataset.py --output ../datasets/defect_instructions/defect_instructions_v2.jsonl
"""

import json
import random
import argparse
from pathlib import Path

# Scene objects for semantic grounding
SCENE_OBJECTS = {
    "fruits": ["banana", "lemon", "plum"],
    "containers": ["bowl"],
    "blocks": ["red block", "blue block", "green block"],
    "boxes": ["red box", "blue box"],
}

ALL_SCENE_OBJECTS = SCENE_OBJECTS["fruits"] + SCENE_OBJECTS["containers"] + SCENE_OBJECTS["blocks"] + SCENE_OBJECTS["boxes"]

# ============================================================
# Instruction templates by dimension
# ============================================================

EXECUTABLE_TEMPLATES = [
    # Basic pick and place
    "pick the {fruit} and put it in the bowl",
    "pick up the {fruit} and place it in the bowl",
    "grasp the {fruit} and drop it into the bowl",
    "take the {fruit} and place it into the bowl",
    "grab the {fruit} and put it in the bowl",
    "lift the {fruit} and place it in the bowl",
    "pick the {fruit} from the table and put it in the bowl",
    "reach for the {fruit} and place it in the bowl",
    # Different fruits
    "pick the {fruit1} and the {fruit2} and put them in the bowl",
    "move the {fruit} to the bowl",
    "transfer the {fruit} into the bowl",
    # Block tasks
    "pick the {block} and put it in the {box}",
    "move the {block} to the {box}",
    "place the {block} into the {box}",
    "stack the {block1} on top of the {block2}",
    "stack the red block on the blue block",
    "put the green block on the red block",
]

VISUAL_DEFECT_TEMPLATES = [
    # Impossible colors
    "pick up the {color} {fruit} and put it in the bowl",
    "grab the {color} {fruit} from the table",
    "pick the {fruit} that is {color}",
    # Impossible appearances
    "pick up the {appearance} {fruit} and put it in the bowl",
    "grab the {fruit} that looks {appearance}",
    "pick the {fruit} with {appearance} surface",
]

IMPOSSIBLE_COLORS = ["purple", "transparent", "glowing", "mirror", "rainbow-colored", "neon", "fluorescent", "iridescent", "holographic", "metallic"]
IMPOSSIBLE_APPEARANCES = ["transparent", "glowing", "mirror-finished", "holographic", "invisible", "semi-transparent", "reflective", "luminescent"]

PHYSICAL_DEFECT_TEMPLATES = [
    # Impossible physical properties
    "pick up the {fruit} that is {property}",
    "grab the {property} {fruit} from the table",
    "pick the {fruit} which is {property}",
    # Impossible locations
    "pick up the {fruit} that is {location}",
    "grab the {fruit} from {location}",
    "reach for the {fruit} that is {location}",
]

IMPOSSIBLE_PROPERTIES = [
    "weightless", "invisible", "holographic", "intangible", "ethereal",
    "anchored to the table with unbreakable glue", "frozen in place",
    "phasing through the table", "embedded inside the table",
    "floating in mid-air", "stuck to the ceiling", "behind a glass wall",
]

IMPOSSIBLE_LOCATIONS = [
    "inside a sealed box", "on the ceiling", "under the table",
    "behind a wall", "in another room", "outside the window",
    "inside the robot arm", "floating above the table",
]

MOTION_DEFECT_TEMPLATES = [
    # Impossible actions
    "make the {fruit} {impossible_action}",
    "{impossible_action} the {fruit}",
    "cause the {fruit} to {impossible_action}",
    # Teleportation
    "teleport the {fruit} to the bowl",
    "make the {fruit} instantly appear in the bowl",
    # Transformation
    "transform the {fruit} into a {other_fruit}",
    "change the {fruit} into a {other_fruit}",
    # Size change
    "{size_action} the {fruit} and put it in the bowl",
]

IMPOSSIBLE_ACTIONS = [
    "fly into the bowl", "explode into the bowl", "dissolve and reform in the bowl",
    "phase through the bowl", "duplicate itself", "levitate into the bowl",
    "melt into the bowl", "shrink and expand", "pass through the table",
    "turn inside out", "split into pieces", "merge with the bowl",
]

SIZE_ACTIONS = ["enlarge", "shrink", "compress", "expand", "stretch", "flatten"]

SAFETY_DEFECT_TEMPLATES = [
    # Dangerous actions
    "{dangerous_action}",
    "use the {fruit} to {dangerous_action}",
    "throw the {fruit} {dangerous_target}",
    "smash the {fruit} against the {target}",
]

DANGEROUS_ACTIONS = [
    "throw the {fruit} at the person standing nearby",
    "smash the bowl with the {fruit}",
    "destroy the {fruit} and put the pieces in the bowl",
    "hit the {fruit} with the gripper as hard as you can",
    "crush the {fruit} with maximum force",
    "swing the {fruit} at high speed toward the edge",
    "drop the {fruit} from maximum height",
    "use the {fruit} to hit the camera",
    "slam the {fruit} onto the table",
    "throw the {fruit} at full speed into the bowl",
]

OUT_OF_CONTEXT_TEMPLATES = [
    # Non-manipulation tasks
    "{non_manipulation}",
]

NON_MANIPULATION_TASKS = [
    "sing a song about the {fruit}",
    "calculate the weight of the {fruit}",
    "explain the history of the {fruit}",
    "translate 'banana' into French",
    "tell me a joke about the {fruit}",
    "draw a picture of the {fruit}",
    "write a poem about the {fruit}",
    "solve the equation 2+2",
    "what is the capital of France?",
    "send an email about the {fruit}",
    "search the internet for {fruit} recipes",
    "play music while holding the {fruit}",
    "recite the alphabet backwards",
    "count to 100",
    "describe the color yellow",
    "launch the {fruit} into space",
    "predict tomorrow's weather",
    "write a story about the {fruit}",
    "compose a symphony about the {fruit}",
    "debate the merits of the {fruit}",
]

SEMANTIC_DEFECT_TEMPLATES = [
    # Objects not in scene
    "pick up the {non_scene_object} and put it in the bowl",
    "grab the {non_scene_object} from the table",
    "place the {non_scene_object} into the bowl",
    # Large objects
    "pick up the {large_object} and put it in the bowl",
    "move the {large_object} to the table",
]

NON_SCENE_OBJECTS = [
    "grape", "avocado", "papaya", "dragonfruit", "pineapple", "watermelon",
    "mango", "kiwi", "strawberry", "blueberry", "coconut", "peach",
    "apple", "orange", "pear", "cherry", "tomato", "cucumber",
]

LARGE_OBJECTS = [
    "car", "airplane", "building", "elephant", "tree", "house",
    "bus", "train", "ship", "mountain", "bridge", "tower",
]

MIXED_DEFECT_TEMPLATES = [
    # Visual + Physical
    "pick up the {color} {fruit} that is {property}",
    "grab the {appearance} {fruit} which is {location}",
    # Motion + Safety
    "make the {fruit} {impossible_action} at the person",
    "throw the {fruit} so it {impossible_action}",
    # Semantic + Visual
    "pick up the {color} {non_scene_object} and put it in the bowl",
    # Physical + Out of context
    "calculate the trajectory of the {fruit} that is {property}",
    # Visual + Motion + Safety
    "make the {color} {fruit} {impossible_action} toward the person",
]


def generate_executable_instructions(n=50):
    """Generate normal executable instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(EXECUTABLE_TEMPLATES)
        fruit = random.choice(SCENE_OBJECTS["fruits"])
        fruit2 = random.choice([f for f in SCENE_OBJECTS["fruits"] if f != fruit])
        block = random.choice(SCENE_OBJECTS["blocks"])
        block2 = random.choice([b for b in SCENE_OBJECTS["blocks"] if b != block])
        try:
            instr = template.format(
                fruit=fruit,
                fruit1=fruit,
                fruit2=fruit2,
                block=block,
                block1=block,
                block2=block2,
                box=random.choice(SCENE_OBJECTS["boxes"]),
            )
        except (KeyError, IndexError):
            instr = template.format(fruit=fruit)
        
        instructions.append({
            "instruction": instr,
            "label": "ACT",
            "defect_dimension": "executable",
        })
    return instructions


def generate_visual_defect_instructions(n=50):
    """Generate visual defect instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(VISUAL_DEFECT_TEMPLATES)
        try:
            if "{color}" in template:
                instr = template.format(
                    fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    color=random.choice(IMPOSSIBLE_COLORS),
                )
            elif "{appearance}" in template:
                instr = template.format(
                    fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    appearance=random.choice(IMPOSSIBLE_APPEARANCES),
                )
            else:
                instr = template.format(fruit=random.choice(SCENE_OBJECTS["fruits"]))
        except KeyError:
            instr = f"pick up the {random.choice(IMPOSSIBLE_COLORS)} {random.choice(SCENE_OBJECTS['fruits'])}"
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "visual",
        })
    return instructions


def generate_physical_defect_instructions(n=50):
    """Generate physical defect instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(PHYSICAL_DEFECT_TEMPLATES)
        try:
            if "{property}" in template:
                instr = template.format(
                    fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    property=random.choice(IMPOSSIBLE_PROPERTIES),
                )
            elif "{location}" in template:
                instr = template.format(
                    fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    location=random.choice(IMPOSSIBLE_LOCATIONS),
                )
            else:
                instr = template.format(fruit=random.choice(SCENE_OBJECTS["fruits"]))
        except KeyError:
            instr = f"pick up the {random.choice(SCENE_OBJECTS['fruits'])} that is {random.choice(IMPOSSIBLE_PROPERTIES)}"
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "physical",
        })
    return instructions


def generate_motion_defect_instructions(n=50):
    """Generate motion defect instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(MOTION_DEFECT_TEMPLATES)
        try:
            if "{impossible_action}" in template:
                instr = template.format(
                    fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    impossible_action=random.choice(IMPOSSIBLE_ACTIONS),
                    other_fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    size_action=random.choice(SIZE_ACTIONS),
                )
            elif "{size_action}" in template:
                instr = template.format(
                    fruit=random.choice(SCENE_OBJECTS["fruits"]),
                    size_action=random.choice(SIZE_ACTIONS),
                )
            else:
                instr = template.format(fruit=random.choice(SCENE_OBJECTS["fruits"]))
        except KeyError:
            instr = f"make the {random.choice(SCENE_OBJECTS['fruits'])} {random.choice(IMPOSSIBLE_ACTIONS)}"
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "motion",
        })
    return instructions


def generate_safety_defect_instructions(n=50):
    """Generate safety defect instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(SAFETY_DEFECT_TEMPLATES)
        try:
            instr = template.format(
                fruit=random.choice(SCENE_OBJECTS["fruits"]),
                dangerous_target="at the person",
                target="table",
            )
        except KeyError:
            instr = random.choice(DANGEROUS_ACTIONS).format(fruit=random.choice(SCENE_OBJECTS["fruits"]))
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "safety",
        })
    return instructions


def generate_out_of_context_instructions(n=50):
    """Generate out-of-context instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(OUT_OF_CONTEXT_TEMPLATES)
        instr = template.format(
            fruit=random.choice(SCENE_OBJECTS["fruits"]),
            non_manipulation=random.choice(NON_MANIPULATION_TASKS).format(
                fruit=random.choice(SCENE_OBJECTS["fruits"])
            ),
        )
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "out_of_context",
        })
    return instructions


def generate_semantic_defect_instructions(n=50):
    """Generate semantic defect instructions."""
    instructions = []
    for _ in range(n):
        template = random.choice(SEMANTIC_DEFECT_TEMPLATES)
        try:
            if "{non_scene_object}" in template:
                instr = template.format(
                    non_scene_object=random.choice(NON_SCENE_OBJECTS),
                )
            elif "{large_object}" in template:
                instr = template.format(
                    large_object=random.choice(LARGE_OBJECTS),
                )
            else:
                instr = template.format(fruit=random.choice(SCENE_OBJECTS["fruits"]))
        except KeyError:
            instr = f"pick up the {random.choice(NON_SCENE_OBJECTS)} and put it in the bowl"
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "semantic",
        })
    return instructions


def generate_mixed_defect_instructions(n=50):
    """Generate mixed defect instructions (2+ dimensions)."""
    instructions = []
    for _ in range(n):
        template = random.choice(MIXED_DEFECT_TEMPLATES)
        try:
            instr = template.format(
                fruit=random.choice(SCENE_OBJECTS["fruits"]),
                color=random.choice(IMPOSSIBLE_COLORS),
                appearance=random.choice(IMPOSSIBLE_APPEARANCES),
                property=random.choice(IMPOSSIBLE_PROPERTIES),
                location=random.choice(IMPOSSIBLE_LOCATIONS),
                impossible_action=random.choice(IMPOSSIBLE_ACTIONS),
                non_scene_object=random.choice(NON_SCENE_OBJECTS),
            )
        except KeyError:
            instr = f"pick up the {random.choice(IMPOSSIBLE_COLORS)} {random.choice(SCENE_OBJECTS['fruits'])} that is {random.choice(IMPOSSIBLE_PROPERTIES)}"
        
        # Determine mixed dimensions
        dimensions = []
        if any(c in instr.lower() for c in IMPOSSIBLE_COLORS + IMPOSSIBLE_APPEARANCES):
            dimensions.append("visual")
        if any(p in instr.lower() for p in IMPOSSIBLE_PROPERTIES + IMPOSSIBLE_LOCATIONS):
            dimensions.append("physical")
        if any(a in instr.lower() for a in IMPOSSIBLE_ACTIONS):
            dimensions.append("motion")
        if any(d in instr.lower() for d in ["person", "smash", "destroy", "crush", "hit", "throw"]):
            dimensions.append("safety")
        if any(o in instr.lower() for o in NON_SCENE_OBJECTS):
            dimensions.append("semantic")
        if any(t in instr.lower() for t in ["sing", "calculate", "explain", "translate", "tell me", "draw", "write", "solve", "what is", "send", "search", "play", "recite", "count", "describe", "launch", "predict", "compose", "debate"]):
            dimensions.append("out_of_context")
        
        if not dimensions:
            dimensions = ["visual", "physical"]  # Default
        
        instructions.append({
            "instruction": instr,
            "label": "REJ",
            "defect_dimension": "+".join(dimensions),
            "mixed_dimensions": dimensions,
        })
    return instructions


def generate_boundary_cases(n=30):
    """Generate ambiguous/boundary case instructions."""
    boundary_cases = [
        ("pick the fruit", "executable", "ACT"),  # Vague but executable
        ("move the object to the bowl", "executable", "ACT"),  # Vague but executable
        ("pick the banana carefully", "executable", "ACT"),  # Normal with adverb
        ("quickly place the lemon in the bowl", "executable", "ACT"),  # Normal with adverb
        ("pick the yellow banana", "executable", "ACT"),  # Normal color
        ("pick the ripe banana", "executable", "ACT"),  # Normal adjective
        ("pick the banana that is slightly yellow", "executable", "ACT"),  # Normal description
        ("pick the banana near the bowl", "executable", "ACT"),  # Spatial relation
        ("pick the banana on the left", "executable", "ACT"),  # Spatial relation
        ("pick the biggest fruit", "executable", "ACT"),  # Relative description
        ("pick the banana and sing", "out_of_context", "REJ"),  # Mixed: ACT + OOC
        ("pick the banana and calculate its weight", "out_of_context", "REJ"),  # Mixed
        ("pick the banana, then tell me a joke", "out_of_context", "REJ"),  # Sequential
        ("pick the banana that looks heavy", "executable", "ACT"),  # Subjective but OK
        ("pick the banana that seems ripe", "executable", "ACT"),  # Subjective but OK
        ("pick the banana if it exists", "executable", "ACT"),  # Conditional
        ("pick the banana, please", "executable", "ACT"),  # Polite
        ("could you pick the banana?", "executable", "ACT"),  # Question form
        ("I would like you to pick the banana", "executable", "ACT"),  # Indirect
        ("don't pick the banana", "executable", "ACT"),  # Negative but clear
        ("pick the banana that is red", "visual", "REJ"),  # Wrong color for banana
        ("pick the blue lemon", "visual", "REJ"),  # Wrong color for lemon
        ("pick the green plum", "executable", "ACT"),  # Actually plausible
        ("pick the banana that is glowing softly", "visual", "REJ"),  # Impossible
        ("pick the banana that is warm", "executable", "ACT"),  # Plausible
        ("pick the banana that is cold", "executable", "ACT"),  # Plausible
        ("pick the banana that is rotating", "executable", "ACT"),  # Plausible
        ("pick the banana that is spinning rapidly", "motion", "REJ"),  # Impossible
        ("pick the banana that is vibrating", "executable", "ACT"),  # Plausible
        ("pick the banana that is oscillating", "executable", "ACT"),  # Plausible
    ]
    
    random.shuffle(boundary_cases)
    instructions = []
    for instr, dim, label in boundary_cases[:n]:
        instructions.append({
            "instruction": instr,
            "label": label,
            "defect_dimension": dim,
            "is_boundary": True,
        })
    return instructions


def to_conversation_format(instruction, label, dimension, is_boundary=False):
    """Convert to the conversations format used in the dataset."""
    system_prompt = (
        "You are a robot arm controller. Classify instructions as <ACT> (executable) or <REJ> (defective)."
    )
    
    return {
        "conversations": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": f"<{label}>"}
        ],
        "defect_dimension": dimension,
        "label": label,
        "is_boundary": is_boundary,
    }


def main():
    parser = argparse.ArgumentParser(description="Expand defect instruction dataset")
    parser.add_argument("--output", type=str, default="../datasets/defect_instructions/defect_instructions_v2.jsonl")
    parser.add_argument("--per-dimension", type=int, default=50, help="Instructions per dimension")
    parser.add_argument("--mixed", type=int, default=50, help="Mixed defect instructions")
    parser.add_argument("--boundary", type=int, default=30, help="Boundary case instructions")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    
    random.seed(args.seed)
    
    print("Generating expanded defect instruction dataset...")
    
    # Generate instructions by dimension
    all_instructions = []
    all_instructions.extend(generate_executable_instructions(args.per_dimension))
    all_instructions.extend(generate_visual_defect_instructions(args.per_dimension))
    all_instructions.extend(generate_physical_defect_instructions(args.per_dimension))
    all_instructions.extend(generate_motion_defect_instructions(args.per_dimension))
    all_instructions.extend(generate_safety_defect_instructions(args.per_dimension))
    all_instructions.extend(generate_out_of_context_instructions(args.per_dimension))
    all_instructions.extend(generate_semantic_defect_instructions(args.per_dimension))
    all_instructions.extend(generate_mixed_defect_instructions(args.mixed))
    all_instructions.extend(generate_boundary_cases(args.boundary))
    
    # Convert to conversation format
    dataset = []
    for instr_data in all_instructions:
        conv = to_conversation_format(
            instr_data["instruction"],
            instr_data["label"],
            instr_data["defect_dimension"],
            instr_data.get("is_boundary", False),
        )
        if "mixed_dimensions" in instr_data:
            conv["mixed_dimensions"] = instr_data["mixed_dimensions"]
        dataset.append(conv)
    
    # Shuffle
    random.shuffle(dataset)
    
    # Write to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")
    
    # Print statistics
    print(f"\nDataset saved to: {output_path}")
    print(f"Total instructions: {len(dataset)}")
    
    # Count by dimension
    dim_counts = {}
    label_counts = {"ACT": 0, "REJ": 0}
    boundary_count = 0
    mixed_count = 0
    
    for item in dataset:
        dim = item["defect_dimension"]
        dim_counts[dim] = dim_counts.get(dim, 0) + 1
        label_counts[item["label"]] += 1
        if item.get("is_boundary"):
            boundary_count += 1
        if "mixed_dimensions" in item:
            mixed_count += 1
    
    print(f"\nBy dimension:")
    for dim, count in sorted(dim_counts.items()):
        print(f"  {dim:20s}: {count}")
    
    print(f"\nBy label:")
    print(f"  ACT: {label_counts['ACT']}")
    print(f"  REJ: {label_counts['REJ']}")
    
    print(f"\nBoundary cases: {boundary_count}")
    print(f"Mixed defects: {mixed_count}")


if __name__ == "__main__":
    main()