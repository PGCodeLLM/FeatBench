#!/usr/bin/env python3
"""Remove list elements with an 'error' key from evaluation result JSON files."""

import json
import sys
from pathlib import Path


def remove_error_entries(file_path: Path, in_place: bool = False) -> None:
    with open(file_path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"Skipping {file_path}: top-level value is not a list")
        return

    before = len(data)
    filtered = [entry for entry in data if "error" not in entry]
    after = len(filtered)

    print(f"{file_path.name}: {before} -> {after} entries ({before - after} removed)")

    if in_place:
        out_path = file_path
    else:
        out_path = file_path.with_stem(file_path.stem + "_cleaned")

    with open(out_path, "w") as f:
        json.dump(filtered, f, indent=2)

    print(f"  Written to: {out_path}")


def main():
    args = sys.argv[1:]

    if not args:
        # Default: process all evaluation_results_*.json files in docker_agent/
        root = Path(__file__).parent.parent / "docker_agent"
        files = sorted(root.glob("evaluation_results_*.json"))
        if not files:
            print("No evaluation_results_*.json files found.")
            sys.exit(1)
    else:
        in_place = "--in-place" in args
        args = [a for a in args if a != "--in-place"]
        files = [Path(a) for a in args]
        for file_path in files:
            remove_error_entries(file_path, in_place=in_place)
        return

    in_place = "--in-place" in sys.argv
    for file_path in files:
        remove_error_entries(file_path, in_place=in_place)


if __name__ == "__main__":
    main()
