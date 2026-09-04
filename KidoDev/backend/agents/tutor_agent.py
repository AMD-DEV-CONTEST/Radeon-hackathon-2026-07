"""
Tutor Agent — Multi-turn, memory-aware coding tutor for kids.
Uses ReAct loop to reason about workspace state before giving a hint.
"""
import json
import re
from typing import Dict, Any, List

from inference import qwen_client
from memory.short_term import short_term_memory
from memory.long_term import load_memory, update_memory, append_observation, log_agent_action
from tools.registry import (
    get_workspace_blocks, get_solution_xml, get_lesson_details,
    get_agent_memory, get_student_profile,
)
from models.schemas import TutorRequest, TutorResponse


SYSTEM_PROMPT = """You are KidoBot & Cat Co-Pilot — a warm, encouraging Socratic Visual AI Coding Tutor and Co-Pilot for children aged 6-14.

Your personality:
- Friendly, enthusiastic, and super supportive. No emojis. No baby talk.
- Follow Socratic pedagogical guidance:
  - When the student asks for a general hint (e.g. 'Give me a hint' or 'I need help'): Explain the CONCEPT of what is needed (e.g. 'To get your character moving, you need a block that changes your sprite's position!') WITHOUT blurting out the exact block name.
  - ONLY when the student explicitly asks 'What block next?' or 'Which block?': State the exact block name and UI position (e.g. 'Look in the Motion panel for the Move Steps block and snap it below your Green Flag block!').
- Explain WHY a block is used conceptually in simple, fun terms (e.g. 'Events give your sprite a starting signal', 'Loops repeat actions automatically so you don't copy-paste code!').
- NEVER repeat raw objective titles or internal teacher notes (like 'Child understands...').
- Keep hints short (2-3 sentences max).

CRITICAL RULES:
- DO NOT use emojis.
- DO NOT give the full XML solution or code.
- Always end with an encouraging phrase.
"""


async def run(req: TutorRequest) -> TutorResponse:
    """Main entry point for TutorAgent."""

    # ── 1. Load context in parallel ──────────────────────────────────────────
    workspace_info = await get_workspace_blocks(req.workspace_blocks)
    solution_data = await get_solution_xml(req.lesson_id)
    lesson_data = await get_lesson_details(req.lesson_id)
    long_mem = await get_agent_memory(req.child_id)

    # ── 2. Short-term memory — load prior conversation ───────────────────────
    prior_history = short_term_memory.get_context_messages(req.child_id, req.session_id)
    hint_count = short_term_memory.get_hint_count(req.child_id, req.session_id)

    # ── 3. Build memory context string ───────────────────────────────────────
    weak_blocks = long_mem.get("weak_block_types", [])
    strong_blocks = long_mem.get("strong_block_types", [])
    observations = long_mem.get("observations", [])

    memory_context = ""
    if weak_blocks:
        memory_context += f"This student has struggled with: {', '.join(weak_blocks)}. "
    if strong_blocks:
        memory_context += f"They are good at: {', '.join(strong_blocks)}. "
    if observations:
        memory_context += f"Past observations: {'; '.join(observations[-3:])}."
    if hint_count > 0:
        memory_context += f" This is hint #{hint_count + 1} in this session."

    # ── 4. Compute gap between student blocks and solution ───────────────────
    gap_info = _compute_gap(req.workspace_blocks, solution_data.get("xml", ""), req.objective)

    # ── 5. Build the reasoning prompt ────────────────────────────────────────
    reasoning_trace = []
    reasoning_trace.append(f"Analyzing workspace: {len(req.workspace_blocks)} blocks placed")
    reasoning_trace.append(f"Solution gap: {len(gap_info['missing'])} blocks missing")
    if memory_context:
        reasoning_trace.append(f"Memory context loaded: {memory_context[:80]}...")

    # ── 6. Build messages ────────────────────────────────────────────────────
    messages = []
    for m in prior_history[-6:]:
        messages.append(m)

    child_question = req.user_message or "I need a hint for my next block."

    context_block = f"""
Lesson: {lesson_data.get('title', req.lesson_id)}
Objective: {_clean_objective(req.objective)}

Student's current blocks: {', '.join(req.workspace_blocks) if req.workspace_blocks else 'None placed yet'}

Missing blocks needed: {', '.join(gap_info['missing'][:3]) if gap_info['missing'] else 'Student may have all blocks!'}

Student memory: {memory_context or 'First time using the tutor.'}

Student says: "{child_question}"

If student asks a general hint ("Give me a hint"), explain the conceptual action needed WITHOUT stating the exact block name.
If student asks explicitly ("What block next?"), state the exact block name and location.
Do NOT show XML or code.
Respond in this exact JSON format:
{{
  "message": "Your encouraging hint here (2-3 sentences)",
  "next_block_type": "s_block_type_name",
  "memory_note": "A note referencing past memory, or null"
}}
"""

    result = await qwen_client.get_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=context_block,
        max_tokens=512,
        temperature=0.7,
    )

    raw = result.get("text", "").strip()
    reasoning_trace.append("Generated hint via agent reasoning engine")

    # ── 7. Parse response ─────────────────────────────────────────────────────
    parsed_json = None
    if raw and not raw.startswith("Qwen2.5") and "model ready at" not in raw:
        try:
            clean = re.sub(r"```json|```", "", raw).strip()
            parsed_json = json.loads(clean)
        except Exception:
            if len(raw) > 10 and not raw.startswith("Qwen2.5") and "model ready at" not in raw:
                parsed_json = {"message": raw[:400], "next_block_type": gap_info["missing"][0] if gap_info["missing"] else None}

    if parsed_json and parsed_json.get("message") and not parsed_json.get("message", "").startswith("Qwen2.5"):
        hint_message = parsed_json.get("message")
        next_block_type = parsed_json.get("next_block_type") or (gap_info["missing"][0] if gap_info["missing"] else None)
        memory_note = parsed_json.get("memory_note")
    else:
        smart_fallback = _generate_smart_fallback_hint(req, gap_info, lesson_data, memory_context)
        hint_message = smart_fallback["message"]
        next_block_type = smart_fallback["next_block_type"]
        memory_note = smart_fallback["memory_note"]
        reasoning_trace.append("Used KidoBot Smart Context Engine (LLM offline/fallback)")


    tokens_out = result.get("tokens_generated", 0)
    if tokens_out == 0 and hint_message:
        tokens_out = len(hint_message.split())
    latency_val = result.get("latency_ms", 15)

    # ── 8. Update memory ──────────────────────────────────────────────────────
    short_term_memory.push(req.child_id, req.session_id, "user", child_question)
    short_term_memory.push(req.child_id, req.session_id, "assistant", hint_message)

    if gap_info["missing"] and gap_info["missing"][0] not in weak_blocks:
        await append_observation(req.child_id, f"Struggled with {gap_info['missing'][0]}")

    await update_memory(req.child_id, {"hint_count": long_mem.get("hint_count", 0) + 1})

    # ── 9. Log action ─────────────────────────────────────────────────────────
    await log_agent_action(
        child_id=req.child_id,
        agent_name="TutorAgent",
        action=f"Delivered hint for lesson {req.lesson_id}",
        tool_used="get_solution_xml,get_agent_memory",
        tokens_generated=tokens_out,
        latency_ms=latency_val,
    )

    return TutorResponse(
        hint_message=hint_message,
        next_block_type=next_block_type,
        reasoning_trace=reasoning_trace,
        tools_used=["get_workspace_blocks", "get_solution_xml", "get_agent_memory"],
        tokens_generated=tokens_out,
        latency_ms=latency_val,
        gpuType=result.get("gpu_type", "AMD ROCm GPU (Qwen2.5-1.5B)"),
        agent_memory_note=memory_note,
    )


BLOCK_HUMAN_MAP = {
    "s_when_flag": {
        "name": "Green Flag Event block",
        "category": "Events",
        "concept_hint": "To start your project, you'll need an event block that gives your sprite a starting signal when you click the green flag! Think about how a game starts when a referee blows a whistle.",
        "explicit_hint": "Look in the Events panel for the Green Flag Event block and snap it at the top of your workspace!",
        "why": "Computers need a clear starting signal! Just like a referee blowing a whistle to start a game, the Green Flag tells your character when to start running your code step-by-step.",
        "position": "at the top of your workspace"
    },
    "s_when_key": {
        "name": "Key Pressed Event block",
        "category": "Events",
        "concept_hint": "To let players control your sprite with the keyboard, you'll need a starting block that listens for key presses!",
        "explicit_hint": "Look in the Events panel for the Key Pressed Event block and snap it at the top of your workspace!",
        "why": "Games need player controls! This block listens for key presses so your player can control the character in real time.",
        "position": "at the top of your workspace"
    },
    "s_when_clicked": {
        "name": "Sprite Clicked block",
        "category": "Events",
        "concept_hint": "To make your sprite react when touched, you'll need a starting event block that senses mouse clicks!",
        "explicit_hint": "Look in the Events panel for the Sprite Clicked block and snap it at the top of your workspace!",
        "why": "Touchscreens and mouse clicks need touch detection! This block lets players interact with your sprite directly by clicking on it.",
        "position": "at the top of your workspace"
    },
    "s_broadcast": {
        "name": "Broadcast Message block",
        "category": "Events",
        "concept_hint": "To make your character send a signal to other sprites, you'll need a messaging block from Events!",
        "explicit_hint": "Look in the Events panel for the Broadcast Message block and snap it into your script!",
        "why": "In complex programs, characters talk to each other! Broadcasting sends a signal across your whole project so other sprites can react simultaneously.",
        "position": "below your trigger script"
    },
    "s_repeat": {
        "name": "Repeat Loop block",
        "category": "Control",
        "concept_hint": "To make an action happen multiple times without snapping 10 identical blocks together, you'll need a loop block from Control!",
        "explicit_hint": "Look in the Control panel for the Repeat Loop block and wrap it around your motion blocks!",
        "why": "Instead of snapping 10 identical blocks together, programmers use loops! A repeat block tells the computer to run actions automatically, keeping your code neat.",
        "position": "wrapped around your motion blocks"
    },
    "s_forever": {
        "name": "Forever Loop block",
        "category": "Control",
        "concept_hint": "To keep your code running continuously while your project is live, you'll need a forever loop block from Control!",
        "explicit_hint": "Look in the Control panel for the Forever Loop block and wrap it around your script!",
        "why": "A forever loop keeps running the blocks inside it as long as your project is live. It's essential for background animations and continuous game checks!",
        "position": "wrapped around your main character script"
    },
    "s_if": {
        "name": "If Condition block",
        "category": "Control",
        "concept_hint": "To give your sprite a brain to make decisions, you'll need a condition block from Control that checks if something is true!",
        "explicit_hint": "Look in the Control panel for the If Condition block and place it inside your loop!",
        "why": "An IF block gives your character a brain to make decisions! It checks a condition (like touching a wall) and only acts if the answer is YES.",
        "position": "inside your repeat or forever loop"
    },
    "s_wait": {
        "name": "Wait Timer block",
        "category": "Control",
        "concept_hint": "To add a small pause so human eyes can watch each movement, you'll need a timer block from Control!",
        "explicit_hint": "Look in the Control panel for the Wait Timer block and snap it below your move block!",
        "why": "Computers execute code in milliseconds! The Wait block adds a tiny pause so human eyes can watch each action happen in order.",
        "position": "below your action or move block"
    },
    "s_move": {
        "name": "Move Steps block",
        "category": "Motion",
        "concept_hint": "To get your character walking across the stage, you'll need a block from Motion that moves your sprite forward!",
        "explicit_hint": "Look in the Motion panel for the Move Steps block and snap it directly below your Green Flag block!",
        "why": "Characters don't move on screen unless we give them motion commands! The Move block changes your sprite's position in the direction it is facing.",
        "position": "directly below your Green Flag block"
    },
    "s_turn_r": {
        "name": "Turn Right block",
        "category": "Motion",
        "concept_hint": "To change your sprite's angle or turn it clockwise, you'll need a rotation block from Motion!",
        "explicit_hint": "Look in the Motion panel for the Turn Right block and snap it into your script!",
        "why": "Turning rotates your sprite's facing angle so it walks or points in a new direction on stage.",
        "position": "below your move or event block"
    },
    "s_turn_l": {
        "name": "Turn Left block",
        "category": "Motion",
        "concept_hint": "To steer your sprite counter-clockwise, you'll need a turn block from Motion!",
        "explicit_hint": "Look in the Motion panel for the Turn Left block and snap it into your script!",
        "why": "Turning left changes your character's heading angle so its forward path points toward a new direction.",
        "position": "below your move or event block"
    },
    "s_goto": {
        "name": "Go To Position block",
        "category": "Motion",
        "concept_hint": "To jump your sprite to an exact spot on stage at the start, you'll need a position block from Motion!",
        "explicit_hint": "Look in the Motion panel for the Go to X Y block and snap it near the top of your script!",
        "why": "Setting an initial position makes sure your character resets to the same starting spot every time the game restarts.",
        "position": "snapped right under your Green Flag block"
    },
    "s_change_x": {
        "name": "Change X block",
        "category": "Motion",
        "concept_hint": "To move your sprite horizontally across the stage, you'll need a change X block from Motion!",
        "explicit_hint": "Look in the Motion panel for the Change X block and snap it into your script!",
        "why": "The X-axis measures horizontal position! Changing X moves your character left or right across the stage.",
        "position": "snapped under your Green Flag or inside your loop"
    },
    "s_change_y": {
        "name": "Change Y block",
        "category": "Motion",
        "concept_hint": "To move your sprite vertically up or down, you'll need a change Y block from Motion!",
        "explicit_hint": "Look in the Motion panel for the Change Y block and snap it into your script!",
        "why": "The Y-axis measures vertical position! Changing Y makes your character jump up or fall down.",
        "position": "snapped under your Green Flag or inside your loop"
    },
    "s_bounce": {
        "name": "Bounce If On Edge block",
        "category": "Motion",
        "concept_hint": "To keep your sprite inside the stage boundaries, you'll need a boundary block from Motion!",
        "explicit_hint": "Look in the Motion panel for the Bounce If On Edge block and place it inside your loop!",
        "why": "Without boundary limits, sprites would wander off the screen! Bounce keeps your character inside the stage bounds.",
        "position": "inside your movement loop"
    },
    "s_say": {
        "name": "Say Message block",
        "category": "Looks",
        "concept_hint": "To make your character talk or display a speech bubble, you'll need a communication block from Looks!",
        "explicit_hint": "Look in the Looks panel for the Say block and snap it into your script!",
        "why": "Characters communicate visually! The Say block pops up a speech bubble so players can read what your character is saying.",
        "position": "snapped below your movement block"
    },
    "s_switch_costume": {
        "name": "Switch Costume block",
        "category": "Looks",
        "concept_hint": "To change your sprite's outfit or pose, you'll need a costume block from Looks!",
        "explicit_hint": "Look in the Looks panel for the Switch Costume block and snap it into your script!",
        "why": "Costumes change how your character looks! Switching costumes lets your sprite change outfits, poses, or expressions.",
        "position": "inside your animation sequence"
    },
    "s_next_costume": {
        "name": "Next Costume block",
        "category": "Looks",
        "concept_hint": "To animate your character's legs as it moves, you'll need a costume animation block from Looks!",
        "explicit_hint": "Look in the Looks panel for the Next Costume block and snap it inside your repeat loop!",
        "why": "Animation works just like a flip-book! Rapidly switching costumes makes your character look like it's walking or dancing.",
        "position": "inside your repeat loop next to your Move block"
    },
    "s_touching": {
        "name": "Touching Object block",
        "category": "Sensing",
        "concept_hint": "To sense when your sprite touches an edge or target, you'll need a collision block from Sensing!",
        "explicit_hint": "Look in the Sensing panel for the Touching Object block and place it inside your If block!",
        "why": "Games need collision detection! This senses when two objects touch so your program can score points or react.",
        "position": "inserted into your If block"
    },
    "s_set_var": {
        "name": "Set Variable block",
        "category": "Variables",
        "concept_hint": "To keep track of points or scores in your game, you'll need a variable block from Variables!",
        "explicit_hint": "Look in the Variables panel for the Set Variable block and snap it at the start of your code!",
        "why": "Variables are like labeled storage boxes! They remember important values like your score or health while the game runs.",
        "position": "snapped under Green Flag"
    },
}


import random

OPENERS_WHY = [
    "Ooh, that is such a great question!",
    "Aha! Love how curious you are!",
    "That is a super smart question to ask!",
    "I love when coders ask why!",
]

OPENERS_WHAT = [
    "Woohoo! Let's check what cool block comes next!",
    "Super work so far! Here is your next coding move:",
    "You are building something awesome! Next up:",
    "Aha, here is the magic piece you need:",
]

OPENERS_STUCK = [
    "No worries at all, coding explorer!",
    "Don't fret, every master programmer gets stuck sometimes!",
    "Take a deep breath, we can solve this together!",
    "I'm right here with you, let's break it down!",
]

OPENERS_HI = [
    "Hello super coder! Ready to make magic on stage?",
    "Hey there explorer! I'm super excited to code with you!",
    "Hi coding buddy! What awesome thing are we making today?",
]

OPENERS_THANKS = [
    "You are so very welcome! Keep shining!",
    "High five! You're an absolute star!",
    "Anytime, coding buddy! You're doing amazing!",
]

ENDINGS = [
    "Give it a spin and see the magic happen!",
    "You've got this, coding superstar!",
    "Snap it into place and see your code run!",
    "Keep up the incredible work!",
    "Can't wait to see your sprite in action!",
]


def _clean_objective(obj_str: str) -> str:
    """Strip teacher notes, evaluation guidelines, and clean objective text for kids."""
    if not obj_str:
        return ""
    clean = re.split(r'Child understands|Teacher note|Assessment:|Objectives:|Goal:', obj_str, flags=re.IGNORECASE)[0]
    return clean.strip().rstrip('!.:')


def _generate_smart_fallback_hint(req, gap_info: dict, lesson_data: dict, memory_context: str) -> dict:
    """Generate dynamic, context-aware hint with a warm, Socratic tutor persona."""
    missing_blocks = gap_info.get("missing", [])
    question = (req.user_message or "").strip().lower()
    ending = random.choice(ENDINGS)

    # Greetings & gratitude (use exact word boundaries so 'hint' does not match 'hi')
    if re.search(r'\b(hi|hello|hey|greetings)\b', question) and not re.search(r'\b(hint|block|help)\b', question):
        return {
            "message": f"{random.choice(OPENERS_HI)} {ending}",
            "next_block_type": missing_blocks[0] if missing_blocks else None,
            "memory_note": "Welcomed child."
        }

    if re.search(r'\b(thanks|thank you|thx)\b', question):
        return {
            "message": f"{random.choice(OPENERS_THANKS)} {ending}",
            "next_block_type": missing_blocks[0] if missing_blocks else None,
            "memory_note": "Encouraged child."
        }

    if not missing_blocks:
        congrats = [
            "Woohoo! You have placed all required blocks for this objective!",
            "High five! You solved the block puzzle like a champion!",
            "Sensational job! Your code looks complete for this challenge!",
        ]
        return {
            "message": f"{random.choice(congrats)} Click the Green Flag to run your program! {ending}",
            "next_block_type": None,
            "memory_note": "Objective completed."
        }

    next_block = missing_blocks[0]
    info = BLOCK_HUMAN_MAP.get(
        next_block,
        {
            "name": f"'{next_block}' block",
            "category": "Toolbox",
            "concept_hint": f"To move forward in your challenge, you'll need a block from the {next_block} section to help your sprite!",
            "explicit_hint": f"Look in the toolbox for the {next_block} block and snap it into your script!",
            "why": f"The {next_block} block is a key building block for your program!",
            "position": "into your script"
        }
    )

    is_why = any(w in question for w in ["why", "reason", "how come", "why use"])
    is_explicit = any(w in question for w in ["what block", "which block", "exact block", "name of block", "what is the block"])

    if is_why:
        opener = random.choice(OPENERS_WHY)
        message = f"{opener} {info['why']} Place it {info['position']}! {ending}"
    elif is_explicit:
        opener = random.choice(OPENERS_WHAT)
        message = f"{opener} {info['explicit_hint']} {info['why']} {ending}"
    else:
        # General hint request ("give me a hint", "hint", "help", "what should i do")
        opener = random.choice(["Hi coding buddy!", "Great question!", "Here is a helpful clue for your project!", "You are doing super so far!"])
        message = f"{opener} {info['concept_hint']} {ending}"

    return {
        "message": message,
        "next_block_type": next_block,
        "memory_note": f"Guided toward {info['name']}."
    }




def _compute_gap(student_blocks: List[str], solution_xml: str, objective: str = "") -> Dict[str, List[str]]:
    """Extract missing blocks by diffing student blocks against solution XML or objective keywords."""
    solution_blocks = []
    if solution_xml:
        import re
        solution_blocks = re.findall(r'type="([^"]+)"', solution_xml)
        solution_blocks = [b for b in solution_blocks if b not in ("math_number", "text")]

    if not solution_blocks:
        # Deduce essential block sequence from objective keywords
        obj = (objective or "").lower()
        solution_blocks = ["s_when_flag"]
        if "move" in obj or "walk" in obj or "step" in obj or "go" in obj or "right" in obj or "left" in obj:
            solution_blocks.append("s_move")
        if "repeat" in obj or "loop" in obj or "times" in obj:
            solution_blocks.append("s_repeat")
        if "forever" in obj or "continuous" in obj:
            solution_blocks.append("s_forever")
        if "say" in obj or "talk" in obj or "speak" in obj or "hello" in obj:
            solution_blocks.append("s_say")
        if "turn" in obj or "rotate" in obj:
            solution_blocks.append("s_turn_r")
        if len(solution_blocks) == 1:
            solution_blocks.append("s_move")

    solution_set = list(dict.fromkeys(solution_blocks))   # preserve order, dedupe
    student_set = set(student_blocks or [])

    missing = [b for b in solution_set if b not in student_set]
    extra = [b for b in (student_blocks or []) if b not in set(solution_blocks)]
    matching = [b for b in (student_blocks or []) if b in set(solution_blocks)]

    return {"missing": missing, "extra": extra, "matching": matching}

