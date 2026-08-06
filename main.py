"""GraphVoice - Voice-driven graph database query assistant.

Usage:
    python main.py              # Interactive voice mode
    python main.py --text       # Text mode (keyboard input)
    python main.py --demo       # Run a demo with preset queries
"""

import argparse
import sys
import tempfile
from pathlib import Path

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.graph_agent import GraphVoiceAgent  # noqa: E402
from database.neo4j_client import Neo4jClient  # noqa: E402
from utils.logger import setup_logging  # noqa: E402

logger = setup_logging("main")


def check_prerequisites() -> bool:
    """Verify Neo4j is reachable."""
    if not Neo4jClient.health_check():
        logger.error("Cannot connect to Neo4j. Run: docker compose up -d")
        return False
    return True


def _detect_lang(text: str) -> str:
    """Heuristic language detection: zh if majority Chinese chars, else en."""
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if chinese_chars > len(text) * 0.3 else "en"


def run_voice_mode():
    """Interactive voice loop."""
    from audio.player import play
    from audio.recorder import record
    from audio.stt_client import transcribe
    from tts.kokoro_tts import synthesize

    print("=" * 50)
    print("  GraphVoice - Voice Interaction Mode")
    print("  Press Enter to record for 6 seconds")
    print("  Type 'quit' or 'exit' to stop")
    print("=" * 50)
    print()

    agent = GraphVoiceAgent()

    with tempfile.TemporaryDirectory() as tmpdir:
        while True:
            try:
                cmd = input("Press Enter to speak (or 'quit'): ").strip()
                if cmd.lower() in ("quit", "exit", "q"):
                    print("Goodbye!")
                    break

                # Step 1: Record for 6 seconds
                audio_path = str(Path(tmpdir) / "input.wav")
                record(audio_path, duration=6.0)

                # Step 2: STT
                print("[Transcribing...]")
                text = transcribe(audio_path)
                if text.startswith("["):
                    print(text)
                    continue
                print(f"You: {text}")

                # Step 3: Agent
                print("[Processing...]")
                answer = agent.process(text)
                print(f"Bot: {answer}")

                # Step 4: TTS + Play
                output_path = str(Path(tmpdir) / "output.aiff")
                print("[Speaking...]")
                # Detect language from answer
                lang = _detect_lang(answer)
                synthesized_path = synthesize(answer, output_path, lang=lang)
                play(synthesized_path)

                print()

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except EOFError:
                print("\nGoodbye!")
                break


def run_text_mode():
    """Interactive text mode."""
    print("=" * 50)
    print("  GraphVoice - Text Mode")
    print("  Type your questions, 'quit' to exit")
    print("=" * 50)
    print()

    agent = GraphVoiceAgent()

    while True:
        try:
            query = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        try:
            answer = agent.process(query)
            print(f"Bot > {answer}")
            print()
        except Exception as e:
            logger.exception("Error processing query")
            print(f"Bot > 抱歉，出错了：{e}")
            print()


def run_demo_mode():
    """Run preset demo queries."""
    from audio.player import play
    from tts.kokoro_tts import synthesize

    print("=" * 50)
    print("  GraphVoice - Demo Mode")
    print("=" * 50)
    print()

    agent = GraphVoiceAgent()

    queries = [
        ("Keanu Reeves 演过哪些电影？", "cn"),
        ("Who directed The Matrix?", "en"),
        ("Tom Hanks starred in what movies?", "en"),
        ("Michael Caine 出演过什么？", "cn"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        for query, lang in queries:
            print(f"[{lang.upper()}] Q: {query}")
            answer = agent.process(query)
            print(f"A: {answer}")

            # Synthesize and play
            output_path = str(Path(tmpdir) / f"output_{hash(query)}.mp3")
            synthesize(answer, output_path, lang=lang)
            play(output_path)
            print()


def main():
    parser = argparse.ArgumentParser(
        description="GraphVoice - Voice-driven graph database assistant"
    )
    parser.add_argument("--text", action="store_true", help="Run in text mode (keyboard input)")
    parser.add_argument("--demo", action="store_true", help="Run a demo with preset queries")
    args = parser.parse_args()

    if not check_prerequisites():
        sys.exit(1)

    if args.text:
        run_text_mode()
    elif args.demo:
        run_demo_mode()
    else:
        run_voice_mode()


if __name__ == "__main__":
    main()
