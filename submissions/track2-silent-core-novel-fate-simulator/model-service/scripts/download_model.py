#!/usr/bin/env python3
"""Download a public Hugging Face model into persistent storage."""

import argparse

from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id")
    parser.add_argument("local_dir")
    args = parser.parse_args()
    path = snapshot_download(args.repo_id, local_dir=args.local_dir)
    print(path)


if __name__ == "__main__":
    main()
