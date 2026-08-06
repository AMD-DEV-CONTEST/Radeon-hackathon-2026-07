import inspect
import json
import subprocess
import re
import time
from pathlib import Path
from typing import Optional

from backend.agent.state import AgentState

from moviepy import VideoFileClip


# PROMPTS

MANIM_CODER_SYSTEM_PROMPT = """You are an expert in Manim Community v0.19. Generate strictly clean, working Python code for ONE scene.

# REQUIREMENTS

## Imports & Class
- Use ONLY: `from manim import *`
- Define exactly ONE class inheriting from `Scene`, named `Scene{scene_id}`.
- Implement `def construct(self):` with all logic inside.

## Allowed Constructs
- Mobjects: Text, MathTex, Tex, MarkupText, Paragraph, Code, Circle, Square, Rectangle, Polygon, RegularPolygon, Arrow, DoubleArrow, Line, Dot, VGroup
- Layout: UP, DOWN, LEFT, RIGHT, ORIGIN, UL, UR, DL, DR
- Colors: WHITE, BLACK, RED, GREEN, BLUE, YELLOW, ORANGE, PURPLE, PINK, GREY, TEAL
- Animations: Create, Write, FadeIn, FadeOut, Transform, ReplacementTransform, GrowFromCenter, Indicate
- Composition: AnimationGroup, Succession, Wait
- Math: MathTex, Tex (MUST ALWAYS use raw strings: e.g., MathTex(r"\frac{1}{2}") )
- Positioning: .to_edge(), .move_to(), .next_to(), .align_to()
- Grouping: VGroup (Use VGroup().arrange(DOWN) to prevent overlapping of multiple elements)
- Modifiers: .scale(), .set_color(), .set_opacity()

## STRICT Constraints
- NO SVGMobject, NO ThreeDScene, NO updaters.
- NO absolute manual coordinates (e.g., avoid LEFT * 3). Rely on .next_to() and .arrange() to prevent overlaps.
- NO external imports (os, sys, requests, etc.).
- ALWAYS prefix MathTex and Tex strings with 'r' (raw string).
- Make sure the animations are fluid and match the narration timing. Avoid abrupt transitions or long pauses.
- Be careful to not overlap text and unwanted elements, and that the positioning is visually appealing, and if you don't use an element anymore remove it.

## Timing
- Use run_time= for animations.
- Use self.wait(1) to separate distinct visual ideas.
- Total scene duration: time length needs to be exactly {scene_duration}.
- The animations should move all along with the narration, so make sure the timing of animations matches the narration positions. The narrator reads around 2 words per second, make sure that the animations are not too fast or too slow compared to the narration and they keep track of the narration.

# OUTPUT FORMAT
Return strictly valid JSON only, with exactly these keys:
- "thought_process": string
- "code": string

Put the Python code inside the "code" field as a fenced block, for example:
"code": "```python\nfrom manim import *\n...\n```"

The JSON object must contain no text outside it. Do not add markdown around the JSON.
The code field must contain only the Manim code needed for the scene.
The thought_process field is for any reasoning text you want to expose.
The code must still start with "from manim import *" after the fence is removed.
"""


MANIM_CODER_USER_TEMPLATE = """Scene {scene_id}: {scene_title}

Visual description: {visual_hint}

Narration (for context): {narration}

{feedback_section}

Generate the scene response as JSON only.
Use a "thought_process" field for any reasoning text and a "code" field for the Python code.
The "code" field must be a fenced Python block.
Do not output anything outside the JSON object.
OUTPUT ONLY ONLY ONLY THE VALID JSON OBJECT, NOTHING ELSE.
A JSON LIKE THIS: {{
    "thought_process": "Here is my reasoning...",
    "code": "```python\\nfrom manim import *\\n...\\n```"
}}
"""


# HELPERS

def _extract_code(response: str) -> str:
    text = response.strip()

    # Remove common reasoning wrappers before extracting code.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    text = re.sub(r"<analysis>.*?</analysis>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    def _strip_code_fences(source: str) -> str:
        candidate = source.strip()
        if "```" in candidate:
            fenced_match = re.search(r"```(?:python)?\s*(.*?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
            if fenced_match:
                return fenced_match.group(1).strip()
        return candidate

    json_candidates = []
    if text.startswith("```"):
        json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if json_match:
            json_candidates.append(json_match.group(1).strip())

    if text.startswith("{") and text.endswith("}"):
        json_candidates.append(text)

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidates.append(text[first_brace:last_brace + 1].strip())

    for candidate in json_candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            code_value = payload.get("code")
            if isinstance(code_value, str) and code_value.strip():
                return _strip_code_fences(code_value)

    # Eliminate ```python ... ```
    if "```python" in text:
        match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Eliminate ``` ... ```
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Keep only the actual Manim source, starting at the required import.
    import_anchor = text.find("from manim import *")
    if import_anchor != -1:
        text = text[import_anchor:]

    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)

    if lines and lines[0].strip() != "from manim import *":
        for index, line in enumerate(lines):
            if line.strip() == "from manim import *":
                lines = lines[index:]
                break

    return "\n".join(lines).strip()


# Save the generated code to a .py file and return the path
def _save_code_to_file(code: str, output_dir: str, scene_id: int) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    file_path = output_path / f"scene_{scene_id}.py"
    file_path.write_text(code, encoding="utf-8")
    return str(file_path)


# Validate the generated code using Track B's validator
def _validate_with_track_b(scene_file: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["python", "-m", "tools.manim.cli", "validate", scene_file],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode == 0:
            return True, ""
        else:
            return False, result.stderr.strip() or result.stdout.strip()
    
    except subprocess.TimeoutExpired:
        return False, "Validation timeout"
    except Exception as e:
        return False, f"Validator error: {e}"


# Render the generated code using Track B's renderer
# Returns (success, error_message, json_output)
def _render_with_track_b(
    scene_file: str, 
    scene_class_name: str, 
    output_video: str
) -> tuple[bool, str, Optional[dict[str, object]]]:
    try:
        result = subprocess.run(
            [
                "python", "-m", "tools.manim.cli", "render",
                scene_file, scene_class_name,
                "--output", output_video,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        if result.returncode == 0:
            try:
                output = json.loads(result.stdout)
                if output.get("success"):
                    return True, "", output
                else:
                    return False, output.get("error", "Unknown render error"), None
            except json.JSONDecodeError:
                if Path(output_video).exists():
                    return True, "", {"video_path": output_video, "duration_sec": 0}
                return False, f"Invalid output from renderer: {result.stdout[:200]}", None
        else:
            return False, result.stderr.strip() or result.stdout.strip(), None
    
    except subprocess.TimeoutExpired:
        return False, "Render timeout (120s)", None
    except Exception as e:
        return False, f"Renderer error: {e}", None


# Fallback code generation for a simple static scene
def _generate_fallback_code(scene_id: int, visual_hint: str) -> str:
    text = visual_hint[:80].replace('"', "'").replace("\n", " ")
    
    return f'''from manim import *

class Scene{scene_id}(Scene):
    def construct(self):
        # Fallback static scene
        title = Text("{scene_id}. Scene", font_size=36, color=BLUE)
        title.to_edge(UP)
        
        body = Text("{text}", font_size=20, color=WHITE)
        body.move_to(ORIGIN)
        body.width = min(body.width, 12)
        
        self.play(Write(title))
        self.play(FadeIn(body))
        self.wait(3)
        self.play(FadeOut(title), FadeOut(body))
'''


# Render a fallback scene if all attempts fail
def _generate_fallback_render(
    scene_id: int,
    visual_hint: str,
    output_dir: str,
) -> tuple[bool, str, Optional[dict[str, object]]]:
    code = _generate_fallback_code(scene_id, visual_hint)
    scene_file = _save_code_to_file(code, output_dir, scene_id)
    scene_class = f"Scene{scene_id}"
    output_video = str(Path(output_dir) / f"scene_{scene_id}.mp4")
    
    return _render_with_track_b(scene_file, scene_class, output_video)


# MAIN NODE

def make_manim_coder_node(llm, output_dir: str = "/tmp/edumanim/scenes", max_retries: int = 2):
    
    def manim_coder_node(state: AgentState) -> AgentState:
        # SETUP
        scenes = state.get("scenes", [])
        current_idx = state.get("current_scene_idx", 0)
        
        if current_idx >= len(scenes):
            return state
        
        scene = scenes[current_idx]
        scene_id = scene.get("id", current_idx + 1)
        scene_title = scene.get("title", f"Scene {scene_id}")
        visual_hint = scene.get("visual_hint", "")
        narration = scene.get("narration", "")
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # RETRY LOOP: generate -> validate -> render
        code = None
        video_path: Optional[str] = None
        last_error = None
        used_fallback = False
        
        for attempt in range(max_retries + 1):
            try:                
                # --- 1. GENERATE code (LLM) ---
                if attempt == 0:
                    feedback = ""
                else:
                    feedback = f"\n\nPREVIOUS ATTEMPT FAILED:\n{last_error}\n\nPlease fix the code and try again."
                
                user_prompt = MANIM_CODER_USER_TEMPLATE.format(
                    scene_id=scene_id,
                    scene_title=scene_title,
                    visual_hint=visual_hint,
                    narration=narration,
                    feedback_section=feedback,
                )

                duration = state["audio_tracks"].get(scene_id, {}).get("duration_sec", 10)
                
                system_prompt = MANIM_CODER_SYSTEM_PROMPT.replace("{scene_id}", str(scene_id)).replace("{scene_duration}", str(duration))
                
                start = time.time()
                response = llm.generate(
                    system_instruction=system_prompt,
                    prompt=user_prompt,
                )
                gen_time = time.time() - start
                
                code = _extract_code(response)
                
                # --- 2. SAVE to file ---
                scene_file = _save_code_to_file(code, output_dir, scene_id)
                
                # --- 3. VALIDATE (Track B) ---
                is_valid, val_error = _validate_with_track_b(scene_file)
                if not is_valid:
                    last_error = f"Validation failed: {val_error}"
                    if attempt < max_retries:
                        continue
                    else:
                        break
                                
                # --- 4. RENDER (Track B) ---
                output_video = str(Path(output_dir) / f"scene_{scene_id}.mp4")
                success, render_error, render_output = _render_with_track_b(
                    scene_file, f"Scene{scene_id}", output_video
                )

                # --- 5. CHECK duration to match with the duration of the audio ---
                duration_real = 0
                if render_output is None:
                    raise RuntimeError("Renderer did not return metadata")

                rendered_video_path = str(render_output.get("video_path", output_video))
                with VideoFileClip(rendered_video_path) as clip:
                    duration_real = clip.duration

                print(f"Scene {scene_id} rendered in {gen_time:.2f}s. Expected duration: {duration:.2f}s, actual: {duration_real:.2f}s.\n\n")
            
                if abs(duration - duration_real) > 1:
                    success = False
                    last_error = f"Duration mismatch: expected {duration}, got {duration_real}. Make sure the animations match the narration timing ({duration} seconds)."

                
                if success:
                    video_path = rendered_video_path
                    break
                else:
                    last_error = f"Render failed: {render_error}"
                    if attempt < max_retries:
                        continue
                    else:
                        break
            
            except Exception as e:
                print(f"Exception during Manim Coder node: {e}")
                last_error = f"{type(e).__name__}: {str(e)}"
                if attempt < max_retries:
                    continue
                else:
                    break
        
        # FALLBACK if all attempts fail
        if video_path is None:
            used_fallback = True
            
            success, fb_error, fb_output = _generate_fallback_render(
                scene_id, visual_hint, output_dir
            )
            
            if success and fb_output:
                video_path = str(fb_output.get("video_path", ""))
                code = _generate_fallback_code(scene_id, visual_hint)
            else:
                state["errors"] = state.get("errors", []) + [
                    f"Manim Coder scene {scene_id}: all attempts + fallback failed. Last: {last_error}, Fallback: {fb_error}"
                ]
                video_path = None
        
        # UPDATE STATE
        scene_codes = state.get("scene_codes", {})
        scene_videos = state.get("scene_videos", {})
        
        if code:
            scene_codes[scene_id] = code
        if video_path:
            scene_videos[scene_id] = video_path
        
        state["scene_codes"] = scene_codes
        state["scene_videos"] = scene_videos
        state["current_scene_idx"] = current_idx + 1
        state["needs_retry"] = False
        state["last_error"] = None
        state["retries_for_current_scene"] = 0
        state["used_fallback"] = state.get("used_fallback", False) or used_fallback
        
        return state
    
    return manim_coder_node


# HELPER: process ALL scenes

async def process_all_scenes(
    state: AgentState,
    llm,
    output_dir: str = "/tmp/edumanim/scenes",
    max_retries: int = 2,
    progress_callback=None,
) -> AgentState:
    total = len(state.get("scenes", []))
    
    manim_coder = make_manim_coder_node(llm, output_dir, max_retries)
    
    for i in range(total):
        print(f"Processing scene {i + 1}/{total}...")

        state = manim_coder(state)
        
        scene_id = state["scenes"][i].get("id", i + 1)
        video = state["scene_videos"].get(scene_id)

        if progress_callback is not None:
            callback_result = progress_callback("manim_scene_done", {
                "scene_id": scene_id,
                "video_path": video,
                "progress": (i + 1) / total,
            })
            if inspect.isawaitable(callback_result):
                await callback_result
        print(f"Scene {i + 1}/{total} done. Video: {video}\n\n")
    
    return state
