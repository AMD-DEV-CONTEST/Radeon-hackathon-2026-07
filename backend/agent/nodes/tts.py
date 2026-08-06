import asyncio
from pathlib import Path
from typing import Any, Dict

from backend.agent.state import AgentState
from tools.tts.synthesize import Synthesizer, SynthesisError, _wav_duration


# HELPERS

def _synthesize_sync(
    synthesizer: Synthesizer,
    text: str,
    output_path: str,
    voice: str = "narrator",
    language: str = "en",
) -> Dict[str, Any]:
    """
    Synchronous TTS synthesis using a cached Synthesizer instance.

    Returns:
        {"success": bool, "audio_path": str, "duration_sec": float, "error": str|None}
    """

    try:
        print("Calling TTS engine with text:", text, "\n\n", "Voice: ", voice, flush=True)
        audio_path = synthesizer.synthesize(text, output_path, voice=voice, language=language)
        print("TTS engine returned:", audio_path, "\n\n", flush=True)
        return {
            "success": True,
            "audio_path": audio_path,
            "duration_sec": _wav_duration(audio_path),
            "error": None,
        }
    except SynthesisError as exc:
        print(f"TTS synthesis error: {exc}\n\n", flush=True)
        return {
            "success": False,
            "audio_path": None,
            "duration_sec": 0,
            "error": str(exc),
        }
    except Exception as e:
        print(f"TTS engine exception: {type(e).__name__}: {str(e)}\n\n", flush=True)
        return {
            "success": False,
            "audio_path": None,
            "duration_sec": 0,
            "error": f"{type(e).__name__}: {str(e)}",
        }


def _list_voices_sync() -> list:
    """Obtains the list of available voices by calling the TTS CLI."""
    try:
        result = subprocess.run(
            ["python", "-m", "tools.tts.cli", "list-voices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else []
    except Exception as e:
        pass
    return []


# MAIN NODE

def make_tts_node(
    output_dir: str = "/tmp/edumanim/audio",
    voice: str = "narrator",
    language: str = "en",
    timeout_per_scene: int = 1800,
):  
    async def tts_node(state: AgentState) -> AgentState:
        scenes = state.get("scenes", [])
        
        if not scenes:
            return state

        print(f"Starting TTS synthesis for {len(scenes)} scenes with voice '{voice}' and language '{language}'...\n\n", flush=True)
                
        # Setup output dir
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        print("Initializing TTS engine once for all scenes...\n\n", flush=True)
        synthesizer = await asyncio.to_thread(Synthesizer)
        print("TTS engine initialized.\n\n", flush=True)
        
        # Prepare async tasks for each scene
        async def synthesize_scene(scene: dict) -> tuple[int, dict]:
            scene_id = scene.get("id", 0)
            scene_title = scene.get("title", f"Scene {scene_id}")
            narration = scene.get("narration", "").strip()
            
            if not narration:
                return scene_id, {
                    "success": False,
                    "audio_path": None,
                    "duration_sec": 0,
                    "error": "Empty narration",
                }
            
            audio_file = str(output_path / f"narration_{scene_id}.wav")

            print(f"Synthesizing TTS for scene {scene_id} ('{scene_title}') to '{audio_file}'...\n\n", flush=True)
            
            # Call Track B in a thread pool (does not block event loop)
            result = await asyncio.to_thread(
                _synthesize_sync,
                synthesizer,
                narration,
                audio_file,
                voice,
                language,
            )

            print(scene_id, scene_title, result, "\n\n", flush=True)
            
            return scene_id, result
        
        # Run all scenes (sequentially because in parallel takes too much memory)
        results = []
        for scene in scenes:
            try:
                res = await synthesize_scene(scene)
                results.append(res)
            except Exception as e:
                results.append(e)
        
        # Process results and update state
        audio_tracks = state.get("audio_tracks", {})
        errors = state.get("errors", [])
        
        for result in results:
            if isinstance(result, Exception):
                errors.append(f"TTS task exception: {result}")
                continue

            # Assign audio track if successful
            scene_id, tts_result = result
            if tts_result["success"] and tts_result["audio_path"]:
                audio_tracks[scene_id] = {"path": tts_result["audio_path"], "duration_sec": tts_result["duration_sec"]}
            else:
                errors.append(
                    f"TTS scene {scene_id} failed: {tts_result.get('error', 'unknown')}"
                )
        
        # Update state
        state["audio_tracks"] = audio_tracks
        state["errors"] = errors
        
        return state
    
    return tts_node
