#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mlx_whisper


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_file")
    parser.add_argument("--model", default="mlx-community/whisper-tiny")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    audio_path = Path(args.audio_file)
    if not audio_path.exists():
        print(json.dumps({"error": f"Audio file not found: {audio_path}"}))
        return 1

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=args.model,
        language=args.language,
        condition_on_previous_text=False,
    )
    print(json.dumps({"text": result.get("text", "").strip()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
