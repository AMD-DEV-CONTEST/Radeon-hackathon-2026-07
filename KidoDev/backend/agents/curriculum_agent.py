"""
Curriculum Planner Agent — Personalized learning path + homework generator.
Analyzes a child's history and plans the optimal next lessons.
Generates targeted homework assignments based on identified weaknesses.
"""
import json
import re
from typing import List, Dict, Any

from inference import qwen_client
from memory.long_term import load_memory, log_agent_action
from tools.registry import get_all_lessons, get_completed_lessons, get_student_profile
from models.schemas import CurriculumRequest, CurriculumResponse


# ─── Homework Bank ────────────────────────────────────────────────────────────
# Maps weak block categories to targeted homework missions

HOMEWORK_BANK = {
    "loops": {
        "blocks": ["s_repeat", "s_forever", "s_repeat_until"],
        "missions": [
            {
                "title": "Loop Master Challenge",
                "objective": "Make your sprite walk in a perfect square by using a Repeat loop with Move and Turn blocks. The sprite should return to its starting position!",
                "target_block_types": ["s_when_flag", "s_repeat", "s_move", "s_turn_r"],
                "difficulty": "medium",
                "estimated_minutes": 10,
            },
            {
                "title": "Endless Dance Party",
                "objective": "Create a forever loop that makes your sprite switch between 3 costumes with a wait between each, creating an animated dance!",
                "target_block_types": ["s_when_flag", "s_forever", "s_next_costume", "s_wait"],
                "difficulty": "easy",
                "estimated_minutes": 8,
            },
        ],
    },
    "conditionals": {
        "blocks": ["s_if", "s_if_else", "s_wait_until"],
        "missions": [
            {
                "title": "Decision Detective",
                "objective": "Make your sprite walk forward, and IF it touches the edge, it should bounce back and say 'Oops!' using an If block with edge sensing.",
                "target_block_types": ["s_when_flag", "s_forever", "s_move", "s_if", "s_touching", "s_bounce", "s_say_time"],
                "difficulty": "medium",
                "estimated_minutes": 12,
            },
            {
                "title": "Color Gate Puzzle",
                "objective": "Create a sprite that walks forward and uses If-Else to check if it is touching a red color. If yes, say 'Stop!'. If no, keep moving.",
                "target_block_types": ["s_when_flag", "s_forever", "s_move", "s_if_else", "s_touching_color", "s_say_time"],
                "difficulty": "hard",
                "estimated_minutes": 15,
            },
        ],
    },
    "motion": {
        "blocks": ["s_move", "s_turn_r", "s_turn_l", "s_goto", "s_glide", "s_goto_rand", "s_change_x", "s_change_y", "s_set_x", "s_set_y"],
        "missions": [
            {
                "title": "Motion Explorer",
                "objective": "Navigate your sprite through a path by combining Move, Turn Right, and Turn Left blocks to draw an L-shape on the stage.",
                "target_block_types": ["s_when_flag", "s_move", "s_turn_r", "s_turn_l"],
                "difficulty": "easy",
                "estimated_minutes": 8,
            },
            {
                "title": "Glide Race",
                "objective": "Make your sprite glide smoothly from one corner of the stage to the opposite corner, then glide to a random position.",
                "target_block_types": ["s_when_flag", "s_glide", "s_glide_rand"],
                "difficulty": "easy",
                "estimated_minutes": 6,
            },
        ],
    },
    "events": {
        "blocks": ["s_when_flag", "s_when_key", "s_when_clicked", "s_when_broadcast", "s_broadcast"],
        "missions": [
            {
                "title": "Keyboard Commander",
                "objective": "Set up 4 When Key Pressed events so your sprite moves up, down, left, and right when you press the arrow keys.",
                "target_block_types": ["s_when_key", "s_change_x", "s_change_y"],
                "difficulty": "medium",
                "estimated_minutes": 10,
            },
            {
                "title": "Broadcast Relay",
                "objective": "Create two sprites. Sprite 1 broadcasts a message when clicked. Sprite 2 receives the broadcast and says a greeting.",
                "target_block_types": ["s_when_clicked", "s_broadcast", "s_when_broadcast", "s_say_time"],
                "difficulty": "hard",
                "estimated_minutes": 15,
            },
        ],
    },
    "looks": {
        "blocks": ["s_say", "s_say_time", "s_think", "s_switch_costume", "s_next_costume", "s_change_size", "s_set_size", "s_show", "s_hide"],
        "missions": [
            {
                "title": "Storyteller Studio",
                "objective": "Make your sprite tell a short 3-part story using Say blocks with timed pauses, switching costumes between each part.",
                "target_block_types": ["s_when_flag", "s_say_time", "s_wait", "s_switch_costume"],
                "difficulty": "easy",
                "estimated_minutes": 8,
            },
            {
                "title": "Growing and Shrinking",
                "objective": "Create a loop that makes your sprite grow bigger (change size by 10) five times, then shrink back to normal size.",
                "target_block_types": ["s_when_flag", "s_repeat", "s_change_size", "s_wait", "s_set_size"],
                "difficulty": "medium",
                "estimated_minutes": 10,
            },
        ],
    },
    "variables": {
        "blocks": ["s_set_var", "s_change_var", "s_var_r"],
        "missions": [
            {
                "title": "Score Keeper Quest",
                "objective": "Create a variable called 'score'. When the sprite is clicked, increase the score by 1 and say the current score.",
                "target_block_types": ["s_when_clicked", "s_change_var", "s_say"],
                "difficulty": "medium",
                "estimated_minutes": 10,
            },
            {
                "title": "Countdown Timer",
                "objective": "Set a variable to 10 and create a loop that counts down to 0, saying each number with a 1-second wait between.",
                "target_block_types": ["s_when_flag", "s_set_var", "s_repeat", "s_say_time", "s_change_var", "s_wait"],
                "difficulty": "hard",
                "estimated_minutes": 12,
            },
        ],
    },
    "sensing": {
        "blocks": ["s_touching", "s_touching_color", "s_color_touching", "s_dist_to", "s_ask", "s_answer", "s_key_pressed", "s_mouse_down"],
        "missions": [
            {
                "title": "Ask and Answer",
                "objective": "Use the Ask block to ask the user their name, then use the Answer block inside a Say block to greet them personally.",
                "target_block_types": ["s_when_flag", "s_ask", "s_say", "s_answer"],
                "difficulty": "easy",
                "estimated_minutes": 8,
            },
        ],
    },
    "timing": {
        "blocks": ["s_wait", "s_broadcast_wait"],
        "missions": [
            {
                "title": "Timing Maestro",
                "objective": "Create a traffic light sequence: show red (wait 3s), show yellow (wait 1s), show green (wait 3s) using costumes and wait blocks.",
                "target_block_types": ["s_when_flag", "s_switch_costume", "s_wait"],
                "difficulty": "medium",
                "estimated_minutes": 10,
            },
        ],
    },
}


SYSTEM_PROMPT = """You are an expert curriculum designer for a kids coding education platform.
CRITICAL RULE: DO NOT use any emojis.
Your task: Analyze a student's learning history and create a personalized learning path WITH targeted homework.

Given:
- Student profile (XP, level, badges)
- Completed lessons with scores
- Weak and strong block types (from agent memory)
- All available lessons

Create a personalized learning plan. Respond ONLY with valid JSON:
{
  "recommended_lessons": [
    {"lesson_id": "L1P2", "title": "Lesson title", "reason": "Why this lesson is recommended", "priority": "high"}
  ],
  "homework_assignments": [
    {
      "title": "Loop Master Challenge",
      "objective": "Build a sprite that walks in a square using repeat loops",
      "target_block_types": ["s_repeat", "s_move", "s_turn_r"],
      "difficulty": "medium",
      "estimated_minutes": 10,
      "reason": "You needed hints on loops 3 times — this mission will strengthen your loop skills"
    }
  ],
  "learning_path_summary": "2-3 sentence summary of the student's progress and next steps.",
  "skill_gaps": ["skill gap 1", "skill gap 2"],
  "strengths": ["strength 1", "strength 2"],
  "next_challenge": "The specific skill or concept to focus on next.",
  "weekly_goal": "A realistic goal for the next 7 days."
}
"""


def _generate_homework_from_weaknesses(weak_blocks: List[str], helped_map: Dict[str, int]) -> List[Dict[str, Any]]:
    """
    Deterministic homework generator: maps weak block types to targeted missions.
    Returns 1-3 homework assignments based on the student's weakest areas.
    """
    homework = []
    matched_categories = set()

    for block in weak_blocks:
        if len(homework) >= 3:
            break

        for category, data in HOMEWORK_BANK.items():
            if category in matched_categories:
                continue
            if block in data["blocks"]:
                mission = data["missions"][0].copy()  # take the first mission
                hint_count = helped_map.get(block, 1)

                # Pick harder mission if they struggled a lot
                if hint_count >= 3 and len(data["missions"]) > 1:
                    mission = data["missions"][1].copy()

                block_label = block.replace("s_", "").replace("_", " ").title()
                mission["reason"] = f"You needed hints on {block_label} blocks {hint_count} time(s) — this mission will build your confidence with them!"

                homework.append(mission)
                matched_categories.add(category)
                break

    # If no weak blocks identified, add a general challenge
    if not homework:
        homework.append({
            "title": "Creative Free Build",
            "objective": "Build any project you want using at least 5 different block types. Show off your coding creativity!",
            "target_block_types": ["s_when_flag", "s_move", "s_repeat", "s_say_time", "s_if"],
            "difficulty": "medium",
            "estimated_minutes": 15,
            "reason": "Great work so far! This open-ended challenge lets you practice all your skills together.",
        })

    return homework


async def run(req: CurriculumRequest) -> CurriculumResponse:
    """Main entry point for CurriculumPlannerAgent."""

    print(f"\n[CurriculumAgent] Executing learning path synthesis for child: '{req.child_id}'")
    reasoning_trace = []

    # ── 1. Load all context ───────────────────────────────────────────────────
    reasoning_trace.append("Loading student profile and lesson database...")
    all_lessons = await get_all_lessons()
    db_completed = await get_completed_lessons(req.child_id)
    long_mem = await load_memory(req.child_id)
    profile = await get_student_profile(req.child_id)

    # Convert request payload completed lessons to dicts
    payload_completed = []
    if req.completed_lessons:
        for c in req.completed_lessons:
            if hasattr(c, "dict"):
                payload_completed.append(c.dict())
            elif isinstance(c, dict):
                payload_completed.append(c)

    # Merge database and payload completed lessons
    completed_map = {}
    for c in db_completed:
        l_id = c.get("lesson_id")
        if l_id:
            completed_map[l_id] = c
    for c in payload_completed:
        l_id = c.get("lesson_id") or c.get("id")
        if l_id:
            completed_map[l_id] = c

    completed = list(completed_map.values())
    print(f"[CurriculumAgent] Database + Payload completed count: {len(completed)}")

    reasoning_trace.append(f"Found {len(all_lessons)} total lessons, {len(completed)} completed")

    # ── 2. Build context for the planner ─────────────────────────────────────
    completed_ids = {c.get("lesson_id") for c in completed if c.get("lesson_id")}
    uncompleted = [l for l in all_lessons if l.get("id") not in completed_ids]
    reasoning_trace.append(f"Identified {len(uncompleted)} uncompleted lessons")

    # Extract weak blocks from helped_block_types if not provided
    helped_map = {}
    for c in completed:
        h_list = c.get("helped_block_types") or c.get("helpedBlocks") or []
        if isinstance(h_list, list):
            for b in h_list:
                helped_map[b] = helped_map.get(b, 0) + 1

    extracted_weak = [b for b, _ in sorted(helped_map.items(), key=lambda x: x[1], reverse=True)]
    weak_blocks = req.weak_block_types or extracted_weak or long_mem.get("weak_block_types", [])
    strong_blocks = req.strong_block_types or long_mem.get("strong_block_types", [])

    scores = [float(c.get("score", 0)) for c in completed if c.get("score") is not None]
    avg_score = (sum(scores) / len(scores)) if scores else 85.0

    print(f"[CurriculumAgent] Analyzing gaps: Weak blocks={weak_blocks}, Strong blocks={strong_blocks}, Avg score={avg_score:.1f}%")

    # ── 3. Generate homework from weakness analysis ──────────────────────────
    homework = _generate_homework_from_weaknesses(weak_blocks, helped_map)
    reasoning_trace.append(f"Generated {len(homework)} targeted homework assignments based on weakness analysis")
    print(f"[CurriculumAgent] Generated {len(homework)} homework assignments: {[h['title'] for h in homework]}")

    user_prompt = f"""Student Profile:
- Level: {req.current_level or profile.get('level', 'Bronze')}
- Total XP: {req.total_xp or profile.get('total_xp', 0)}
- Average Score: {avg_score:.1f}%
- Weak Block Types: {', '.join(weak_blocks) or 'None'}
- Strong Block Types: {', '.join(strong_blocks) or 'None'}

Completed Lessons ({len(completed)}):
{json.dumps(completed[-10:], indent=2)}

All Available Lessons ({len(all_lessons)} total). Uncompleted ({len(uncompleted)}):
{json.dumps(uncompleted[:15], indent=2)}

Create a personalized curriculum plan for this student. Recommend 3-5 specific uncompleted lessons from the list above, prioritized by their current skill level and gaps. Also generate 1-3 homework assignments that target their weak block types."""

    print(f"[CurriculumAgent] Requesting completion from inference engine...")
    result = await qwen_client.get_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=1024,
        temperature=0.4,
    )

    raw = result.get("text", "").strip()
    print(f"[CurriculumAgent] Completion finished ({result.get('tokens_generated', 0)} tokens in {result.get('latency_ms', 0)}ms)")
    reasoning_trace.append(f"Generated personalized curriculum via {result.get('provider', 'inference engine')}")


    # ── 4. Parse response ─────────────────────────────────────────────────────
    recommended = []
    llm_homework = []
    summary = ""
    skill_gaps = []
    strengths = []
    next_challenge = ""
    weekly_goal = ""

    try:
        clean = re.sub(r"```json|```", "", raw).strip()
        parsed = json.loads(clean)
        recommended = parsed.get("recommended_lessons", [])
        llm_homework = parsed.get("homework_assignments", [])
        summary = parsed.get("learning_path_summary", "")
        skill_gaps = parsed.get("skill_gaps", [])
        strengths = parsed.get("strengths", [])
        next_challenge = parsed.get("next_challenge", "")
        weekly_goal = parsed.get("weekly_goal", "")
    except Exception as e:
        reasoning_trace.append(f"Failed to parse LLM response JSON: {str(e)}")

    # ── Merge LLM homework with deterministic homework (prefer deterministic) ─
    # Use deterministic as base, add any unique LLM-generated ones
    final_homework = list(homework)  # deterministic base
    seen_titles = {h["title"].lower() for h in final_homework}
    for h in llm_homework:
        if isinstance(h, dict) and h.get("title", "").lower() not in seen_titles:
            final_homework.append(h)
            seen_titles.add(h.get("title", "").lower())
    final_homework = final_homework[:3]  # cap at 3

    # ── Ensure non-empty strengths & skill gaps ─────────────────────────────
    gold_count = sum(1 for c in completed if float(c.get("score", 0)) >= 85 or "Gold" in str(c.get("badge", "")))
    count = max(len(completed), int(req.total_xp or 0) // 50)

    if not strengths:
        strengths = []
        if avg_score >= 80:
            strengths.append(f"High Code Accuracy ({avg_score:.0f}% Avg Score)")
        if gold_count > 0:
            strengths.append(f"Gold Badge Mastery ({gold_count} Top Lessons)")
        if count >= 3:
            strengths.append(f"Advanced Level Progress ({count} Missions Completed)")
        if (req.total_xp or 0) >= 150:
            strengths.append(f"Strong Learning Stamina ({req.total_xp} Total XP)")
        if not weak_blocks and count > 0:
            strengths.append("Independent Problem Solving & Execution")
        if len(strengths) < 2:
            strengths.extend(["Visual Block Connection", "Active Platform Engagement"])

    if not skill_gaps:
        skill_gaps = []
        block_name_map = {
            "s_repeat": "Repeat Loops & Iteration",
            "s_forever": "Forever Loops",
            "s_wait": "Wait & Timing Delays",
            "s_if": "If / Else Conditionals",
            "s_touching_color": "Color Touch Sensing",
            "s_goto_xy": "XY Coordinate Positioning",
        }
        for b in weak_blocks:
            label = block_name_map.get(b, b.replace("s_", "").replace("_", " ").title())
            count_h = helped_map.get(b, 1)
            skill_gaps.append(f"{label} (Hint requested {count_h}x)")

        if len(skill_gaps) < 2:
            skill_gaps.extend(["Multi-Sprite Event Signal Broadcasting", "Optimizing Script Execution Speed"])

    if not summary:
        summary = f"Outstanding progress! Your child has completed {count} mission(s) with an average score of {avg_score:.0f}%. They demonstrate strong logical reasoning and master complex programming concepts quickly."

    if not weekly_goal:
        weekly_goal = "Complete 2 new coding challenges this week."

    if not next_challenge:
        next_challenge = "Try using loop and conditional blocks in your next project."

    if not recommended:
        for lesson in uncompleted[:3]:
            recommended.append({
                "lesson_id": lesson.get("id", ""),
                "title": lesson.get("title", "Untitled"),
                "reason": "Recommended next step in curriculum.",
                "priority": "high",
            })
        if not recommended:
            recommended = [
                {"lesson_id": "L1P2", "title": "Loop & Repeat Magic", "reason": "Learn how to repeat actions efficiently", "priority": "high"},
                {"lesson_id": "L1P3", "title": "Obstacle Dodge Challenge", "reason": "Master conditional decision logic", "priority": "medium"}
            ]

    reasoning_trace.append(f"Recommended {len(recommended)} lessons + {len(final_homework)} homework assignments")

    # ── 5. Log ────────────────────────────────────────────────────────────────
    await log_agent_action(
        child_id=req.child_id,
        agent_name="CurriculumPlannerAgent",
        action=f"Generated learning path + {len(final_homework)} homework assignments",
        tool_used="get_all_lessons,get_completed_lessons,homework_bank",
        tokens_generated=result.get("tokens_generated", 0),
        latency_ms=result.get("latency_ms", 0),
    )

    return CurriculumResponse(
        recommended_lessons=recommended,
        homework_assignments=final_homework,
        learning_path_summary=summary,
        skill_gaps=skill_gaps,
        strengths=strengths,
        next_challenge=next_challenge,
        weekly_goal=weekly_goal,
        reasoning_trace=reasoning_trace,
    )
