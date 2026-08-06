from __future__ import annotations
import argparse
import json
import sys
from tools.ffmpeg.assemble import assemble, get_video_info, AssemblyError, FFmpegError


def cmd_assemble(args: argparse.Namespace) -> int:
    try:
        output_path = assemble(
            scenes=args.scenes,
            audios=args.audios,
            output=args.output,
            quality=args.quality,
        )
    except (AssemblyError, FFmpegError) as e:
        print(str(e), file=sys.stderr)
        return 1

    info = get_video_info(output_path)
    print(json.dumps({
        "video_path": output_path,
        "duration_sec": info["duration"],
        "size_mb": round(__import__("os").path.getsize(output_path) / (1024 * 1024), 2),
    }))
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    try:
        info = get_video_info(args.video_path)
    except (AssemblyError, FFmpegError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(info))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.ffmpeg.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    assemble_parser = subparsers.add_parser("assemble", help="Assemble scenes and audios into a final video")
    assemble_parser.add_argument("--scenes", nargs="+", required=True)
    assemble_parser.add_argument("--audios", nargs="+", required=True)
    assemble_parser.add_argument("--output", required=True)
    assemble_parser.add_argument("--quality", default="720p", choices=["720p", "1080p"])
    assemble_parser.set_defaults(func=cmd_assemble)

    info_parser = subparsers.add_parser("info", help="Get info about a video file")
    info_parser.add_argument("video_path")
    info_parser.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())