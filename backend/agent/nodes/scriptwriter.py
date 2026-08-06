from typing import List

from langchain_core.output_parsers import PydanticOutputParser


from backend.agent.state import AgentState, ScriptOutput


# PROMPT

SCRIPTWRITER_SYSTEM_PROMPT = """You are an expert educational scriptwriter specializing in deep-dive, long-form animated mathematical and scientific explainer videos (3-10 minutes total).

## Your task
Given a topic and research notes, write a highly structured, in-depth video script with 5-8 scenes. Do NOT write surface-level summaries; explain the "why" and "how" deeply.

## Scene structure pattern
A deep-dive script follows this arc:
1. **Hook & Intuition** (Scene 1): The real-world problem or paradox.
2. **First Principles** (Scene 2-3): Breaking down the core components or variables.
3. **The Mathematical Core** (Scene 4-5): The exact equations, showing how they morph and transform.
4. **Complex Application/Example** (Scene 6-7): Running real numbers or tracing a full system.
5. **Synthesis** (Scene 8): The grand takeaway.

## For each scene, you must provide:

**title**: 3-6 words defining the scene's exact focus.

**narration** (2-3 sentences, 20-90 words):
- Spoken by voiceover. Write CONVERSATIONALLY but ACADEMICALLY.
- Explain the mechanics deeply. Don't just state facts; walk the viewer through the logic step-by-step.
- Use analogies for abstract concepts, followed by the rigorous definition.
- DO NOT MAKE IT TOO BIG.

**visual_hint** (Dynamic and Manim-native):
- Think in TRANSFORMATIONS, not static slides. Do NOT just say "Text appears". 
- Use Manim's strengths: morphing equations, plotting dynamic graphs on an Axes/NumberPlane, geometric transformations.
- Describe what transforms into what (e.g., "The x in the equation transforms into the number 5, and the graph line curves upwards").
- Use LaTeX for all math: `$\\sigma(x)$`, `$\\frac{{a}}{{b}}$`, `$\\int_0^1 x^2 dx$`.
- Keep it realizable for a Manim coder (focus on 2D geometry, math text, and standard shapes).
- The narrator reads around 2 words per second, so make sure the visual hint is enoughtly detailed to support the full length of the narration of the scene.
- Make sure the visual hint is consistent with the narration. If the narration mentions a specific equation or concept, the visual hint should reflect that.
- CRITICAL: The visual hint must be based on the narration. You need to describe what the viewer sees on screen as the narrator speaks. Do NOT introduce new concepts in the visual hint that are not mentioned in the narration.
- VERY CRITICAL: The number of animations should be enough to cover the entire narration. If the narration is long, the visual hint should have multiple animations that match the narration. If the narration is short, the visual hint should have fewer animations. MAKE SURE TO HAVE ENOUGH ANIMATIONS, I DONT WANT A SIMPLE ANIMATION TO BE USED FOR A LONG NARRATION. Most of the time the visual hint is too short for the narration, so make sure to have enough animations to cover the entire narration.

**key_concepts** (2-4 items): Main ideas covered.

## Output format
JSON object with:
- `title`: string
- `estimated_duration_sec`: integer (sum of scenes at ~150 words/min, should be 200-600)
- `scenes`: array of 5-8 Scene objects (id starts at 1)
- Before writing the scenes, use the thought_process key to calculate your word counts, durations, and scene limits. Then, output the final scenes.

A scene object has:
- `id`: integer (1, 2, 3, ...)
- `title`: string - the scene's title
- `narration`: string - the voiceover script for the scene
- `visual_hint`: string - the visual description for the scene, used to generate Manim code

Critical rules
1. Output ONLY the JSON. No explanations, no markdown fences, no "Here's the script:".

2. id must be 1, 2, 3, ... in order

3. Each scene's narration + visual must make sense TOGETHER.

4. LaTeX uses double backslashes in JSON: $\\\\sigma$ becomes $\\sigma$ when parsed.

5. NEVER use placeholders. Write the actual math equations.
"""




SCRIPTWRITER_USER_TEMPLATE = """Topic: {query}


{research_section}


Write a complete script with 3-5 scenes. Output ONLY the JSON object."""


# Helpers

def _format_research_notes(notes: List[str]) -> str:
    if not notes:
        return "## Research notes\nNone provided. Use your general knowledge."

    return "## Research notes\n" + "\n".join(f"- {n}" for n in notes)



def _count_words(text: str) -> int:
    return len(text.split())



def _estimate_narration_duration(text: str) -> int:
    words = _count_words(text)

    return max(5, int(words / 2.5))



def _validate_script_quality(script: ScriptOutput) -> tuple[bool, List[str]]:
    # Return (is_valid, list_of_warnings).

    warnings = []

    

    # Check 1: min 3 scenes, max 6 scenes

    if len(script.scenes) < 3:
        warnings.append(f"Too few scenes: {len(script.scenes)} (minimum 3)")

    if len(script.scenes) > 6:
        warnings.append(f"Too many scenes: {len(script.scenes)} (maximum 6)")

    

    # Check 2: scene IDs must be consecutive starting from 1

    expected_ids = list(range(1, len(script.scenes) + 1))

    actual_ids = [s.id for s in script.scenes]

    if actual_ids != expected_ids:
        warnings.append(f"Scene IDs not consecutive: {actual_ids}")

    

    # Check 3: Each scene's title, narration, visual_hint must be non-empty and of reasonable length

    for scene in script.scenes:
        """ if not scene.title or len(scene.title) < 3:
            warnings.append(f"Scene {scene.id}: title too short") """

        if not scene.narration or _count_words(scene.narration) < 10:
            warnings.append(f"Scene {scene.id}: narration too short ({_count_words(scene.narration)} words)")

        if _count_words(scene.narration) > 100:
            warnings.append(f"Scene {scene.id}: narration too long ({_count_words(scene.narration)} words)")

        if not scene.visual_hint or len(scene.visual_hint) < 20:
            warnings.append(f"Scene {scene.id}: visual_hint too vague")

    

    # Check 4: estimated_duration should have a reasonable length

    """ actual_total = sum(_estimate_narration_duration(s.narration) for s in script.scenes)

    if abs(script.estimated_duration_sec - actual_total) > 60:
        warnings.append(
            f"Duration estimate off: claimed {script.estimated_duration_sec}s, "

            f"actual ~{actual_total}s"
        ) """

    return len(warnings) == 0, warnings



def _make_fallback_script(query: str) -> ScriptOutput:
    return ScriptOutput(

        title=f"Explanation of {query[:50]}",

        estimated_duration_sec=60,

        scenes=[

            {

                "id": 1,

                "title": "Introduction",

                "narration": f"Today we'll explore {query}. This is a fundamental concept that's worth understanding deeply.",

                "visual_hint": f"Title text fades in: '{query[:40]}'. A simple, clean background. Then transition to the next scene.",

                "key_concepts": [query.lower()],

            },

            {

                "id": 2,

                "title": "Core Concept",

                "narration": f"The main idea behind {query} can be understood by looking at its key components and how they interact with each other.",

                "visual_hint": "Display the core concept in the center. Use simple shapes and labels. Add arrows to show relationships between components.",

                "key_concepts": ["main idea", "components"],

            },

            {

                "id": 3,

                "title": "Summary",

                "narration": f"To summarize, {query} is a concept that helps us understand a specific aspect of this field. With this foundation, you can explore further applications.",

                "visual_hint": "Summary text appears on screen with the key points. Fade to title card.",

                "key_concepts": ["summary"],

            },

        ],

    )


# Main scriptwriter node

def make_scriptwriter_node(llm, max_retries: int = 2):
    parser = PydanticOutputParser(pydantic_object=ScriptOutput)

    def scriptwriter_node(state: AgentState) -> AgentState:
        query = state["user_query"]
        research_notes = state.get("research_notes", [])

        script = None
        last_error = None

        # Retry loop
        for attempt in range(max_retries + 1):
            try:
                # Build the prompt with research notes
                research_section = _format_research_notes(research_notes)

                # On retry, add extra instructions to the prompt to help the LLM correct its output
                if attempt > 0 and last_error:
                    extra_instruction = f"\n\n## PREVIOUS ATTEMPT FAILED\nError: {last_error}\nPlease ensure your output is valid JSON matching the schema exactly."
                else:
                    extra_instruction = ""

                user_prompt = SCRIPTWRITER_USER_TEMPLATE.format(

                    query=query,

                    research_section=research_section,

                ) + extra_instruction

                # Get the LLM response
                response = llm.generate(system_instruction = SCRIPTWRITER_SYSTEM_PROMPT, prompt = user_prompt)
                
                # Parse ca Pydantic
                script = parser.parse(response)

                # Validate quality of the script
                is_valid, warnings = _validate_script_quality(script)

                if is_valid:
                    break
                else:
                    if attempt < max_retries:
                        last_error = f"Quality issues: {'; '.join(warnings)}"
                        continue
                    else:
                        break

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                
                if attempt < max_retries:
                    continue
                else:
                    break

        # POST-RETRY: fallback if all attempts failed
        if script is None:
            script = _make_fallback_script(query)

            state["errors"] = state.get("errors", []) + [
                f"Scriptwriter: all attempts failed, used fallback. Last error: {last_error}"
            ]

        # UPDATE STATE
        state["script"] = script.model_dump()

        state["scenes"] = [scene.model_dump() for scene in script.scenes]

        state["current_scene_idx"] = 0

        state["scene_codes"] = {}  # reset scene codes

        return state

    

    return scriptwriter_node