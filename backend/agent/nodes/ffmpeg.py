import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

from backend.agent.state import AgentState


# HELPERS

def _assemble_sync(
    scene_videos: List[str],
    audio_tracks: List[str],
    output_path: str,
    quality: str = "720p",
    timeout: int = 300,
) -> Dict[str, Any]:
    # Call the FFmpeg CLI to assemble the final video
    # Returns {"success": bool, "video_path": str, "duration_sec": float, "size_mb": float, "error": str|None}

    try:
        cmd = [
            "python", "-m", "tools.ffmpeg.cli", "assemble",
            "--scenes", *scene_videos,
            "--audios", *audio_tracks,
            "--output", output_path,
            "--quality", quality,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "video_path": None,
                "duration_sec": 0,
                "size_mb": 0,
                "error": result.stderr.strip() or result.stdout.strip()[:200],
            }
        
        # Parse JSON output
        try:
            data = json.loads(result.stdout)
            return {
                "success": True,
                "video_path": data.get("video_path", output_path),
                "duration_sec": data.get("duration_sec", 0),
                "size_mb": data.get("size_mb", 0),
                "error": None,
            }
        except json.JSONDecodeError:
            # Fallback: verify if the output file exists
            if Path(output_path).is_file():
                size_mb = Path(output_path).stat().st_size / (1024 * 1024)
                return {
                    "success": True,
                    "video_path": output_path,
                    "duration_sec": 0,
                    "size_mb": round(size_mb, 2),
                    "error": None,
                }
            return {
                "success": False,
                "video_path": None,
                "duration_sec": 0,
                "size_mb": 0,
                "error": "Invalid output from assembler",
            }
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "video_path": None,
            "duration_sec": 0,
            "size_mb": 0,
            "error": f"FFmpeg timeout ({timeout}s)",
        }
    except Exception as e:
        return {
            "success": False,
            "video_path": None,
            "duration_sec": 0,
            "size_mb": 0,
            "error": f"{type(e).__name__}: {str(e)}",
        }


def _get_video_info_sync(video_path: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    # Obtain video info (duration, dimensions, fps)
    try:
        result = subprocess.run(
            ["python", "-m", "tools.ffmpeg.cli", "info", video_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f"Error getting video info for {video_path}: {e}")
    return None


def _validate_inputs(
    scene_videos: Dict[int, str],
    audio_tracks: Dict[int, str],
) -> tuple[bool, List[str]]:
    # Validate that all files exist and are pairable.
    # Returns (is_valid, list_of_errors)

    errors = []
    
    if not scene_videos:
        errors.append("No scene videos provided")
    if not audio_tracks:
        errors.append("No audio tracks provided")

    # Verify that scene IDs match and that all scenes have both video and audio
    if scene_videos.keys() != audio_tracks.keys():
        missing_video = set(audio_tracks.keys()) - set(scene_videos.keys())
        missing_audio = set(scene_videos.keys()) - set(audio_tracks.keys())
        if missing_video:
            errors.append(f"Missing video for scenes: {sorted(missing_video)}")
        if missing_audio:
            errors.append(f"Missing audio for scenes: {sorted(missing_audio)}")
    
    # Verify that files exist
    for scene_id, video_path in scene_videos.items():
        if not Path(video_path).is_file():
            errors.append(f"Scene {scene_id} video not found: {video_path}")
    
    for scene_id, audio_path in audio_tracks.items():
        if not Path(audio_path).is_file():
            errors.append(f"Scene {scene_id} audio not found: {audio_path}")
    
    return len(errors) == 0, errors


# MAIN NODE

def make_ffmpeg_node(
    output_path: str = "/tmp/edumanim/final.mp4",
    quality: str = "720p",
    timeout: int = 300,
):
    
    def ffmpeg_node(state: AgentState) -> AgentState:
        scene_videos = state.get("scene_videos", {})
        audio_tracks_dict = state.get("audio_tracks", {})
        audio_tracks = {sid: audio_tracks_dict[sid]["path"] for sid in sorted(audio_tracks_dict.keys())}
        scenes = state.get("scenes", [])
                
        # Validate inputs
        is_valid, errors = _validate_inputs(scene_videos, audio_tracks)
        if not is_valid:
            state["errors"] = state.get("errors", []) + [f"FFmpeg validation: {errors}"]
            return state
        
        # Order videos and audios by scene_id
        sorted_scene_ids = sorted(scene_videos.keys())
        ordered_videos = [scene_videos[sid] for sid in sorted_scene_ids]
        ordered_audios = [audio_tracks[sid] for sid in sorted_scene_ids]
        
        
        # Setup output
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ASSEMBLE
        import asyncio
        import time
        
        start = time.time()
        
        result = asyncio.run(_assemble_async(
            ordered_videos, ordered_audios, output_path, quality, timeout
        ))
        
        elapsed = time.time() - start
        
        # Processing result
        if result["success"]:
            state["final_video_path"] = result["video_path"]
        else:
            state["errors"] = state.get("errors", []) + [
                f"FFmpeg assembly failed: {result['error']}"
            ]
            state["final_video_path"] = None
        
        return state
    
    return ffmpeg_node


async def _assemble_async(
    videos: List[str],
    audios: List[str],
    output: str,
    quality: str,
    timeout: int,
) -> Dict[str, Any]:
    # Async wrapper over the synchronous _assemble_sync function, using asyncio.to_thread to run it in a separate thread.
    import asyncio
    return await asyncio.to_thread(
        _assemble_sync, videos, audios, output, quality, timeout
    )