import argparse
import json
import sys

try:
    from tools.tts.synthesize import Synthesizer, SynthesisError, list_voices, _wav_duration
except ImportError:
    from synthesize import Synthesizer, SynthesisError, list_voices, _wav_duration  # type: ignore


def _print_json(payload: dict) -> None:
    print(json.dumps(payload))


def _cmd_synthesize(args: argparse.Namespace) -> int:
    try:
        synth = Synthesizer()
        audio_path = synth.synthesize(args.text, args.output, voice=args.voice, language=args.language)
        _print_json({"audio_path": audio_path, "duration_sec": _wav_duration(audio_path)})
        return 0
    except SynthesisError as exc:
        _print_json({"error": str(exc)})
        return 1
    except Exception as exc:
        _print_json({"error": f"Unexpected error during synthesis: {exc}"})
        return 1


def _cmd_list_voices(_args: argparse.Namespace) -> int:
    try:
        _print_json(list_voices())
        return 0
    except Exception as exc:
        _print_json({"error": f"Unexpected error listing voices: {exc}"})
        return 1


def _cmd_preview(args: argparse.Namespace) -> int:
    try:
        synth = Synthesizer()
        audio_path = synth.preview(args.voice_name, args.output)
        _print_json({"audio_path": audio_path, "duration_sec": _wav_duration(audio_path)})
        return 0
    except SynthesisError as exc:
        _print_json({"error": str(exc)})
        return 1
    except Exception as exc:
        _print_json({"error": f"Unexpected error during preview: {exc}"})
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.tts.cli", description="TTS tool for EduManim.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_synth = sub.add_parser("synthesize", help="Convert text to speech.")
    p_synth.add_argument("text", metavar="TEXT")
    p_synth.add_argument("--output", required=True, metavar="PATH")
    p_synth.add_argument("--voice", default="default", metavar="NAME")
    p_synth.add_argument("--language", default="en", metavar="LANG")
    p_synth.set_defaults(func=_cmd_synthesize)

    p_list = sub.add_parser("list-voices", help="List available default voices.")
    p_list.set_defaults(func=_cmd_list_voices)

    p_preview = sub.add_parser("preview", help="Synthesize a short sample of a voice.")
    p_preview.add_argument("voice_name", metavar="VOICE_NAME")
    p_preview.add_argument("--output", required=True, metavar="PATH")
    p_preview.set_defaults(func=_cmd_preview)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())