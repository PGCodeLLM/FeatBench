"""
Convert featbench_v1_0.json patch lists into standard unified git diff strings.

Each entry's `patch` and `test_patch` arrays (per-file hunk objects) are
assembled into a single diff string and replace the original top-level keys
`patch` and `test_patch`.

Output: dataset/featbench_v1_0_standardized.json
"""

import json
import sys
from pathlib import Path
from unidiff import PatchSet

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = REPO_ROOT / "dataset" / "featbench_v1_0.json"
OUTPUT_FILE = REPO_ROOT / "dataset" / "featbench_v1_0_standardized.json"


def build_file_diff(file_patch: dict) -> str:
    """
    Convert a single per-file patch object from the JSON dataset into a
    complete git diff string, mirroring the logic in PatchAnalyzer._build_complete_diff.
    """
    filename: str = file_patch["filename"]
    status: str = file_patch.get("status", "modified")
    patch_content: str = file_patch.get("patch", "")
    old_filename: str | None = file_patch.get("old_filename")

    header = f"diff --git a/{filename} b/{filename}\n"

    if status == "added":
        return (
            f"{header}"
            f"new file mode 100644\n"
            f"index 0000000..1111111\n"
            f"--- /dev/null\n"
            f"+++ b/{filename}\n"
            f"{patch_content}"
        )
    elif status == "removed":
        return (
            f"{header}"
            f"deleted file mode 100644\n"
            f"index 1111111..0000000\n"
            f"--- a/{filename}\n"
            f"+++ /dev/null\n"
            f"{patch_content}"
        )
    elif status == "renamed":
        old_name = old_filename or filename
        return (
            f"diff --git a/{old_name} b/{filename}\n"
            f"similarity index 100%\n"
            f"rename from {old_name}\n"
            f"rename to {filename}\n"
            f"{patch_content}"
        )
    else:  # modified (default)
        return (
            f"{header}"
            f"index 1111111..2222222 100644\n"
            f"--- a/{filename}\n"
            f"+++ b/{filename}\n"
            f"{patch_content}"
        )


def patches_to_diff(patch_list: list[dict]) -> str:
    """Combine multiple per-file patch objects into one unified diff string."""
    if not patch_list:
        return ""
    
    # Build each file diff and join with single newline separator
    file_diffs = []
    for p in patch_list:
        diff = build_file_diff(p)
        # Ensure each diff ends with exactly one newline
        diff = diff.rstrip("\n") + "\n"
        file_diffs.append(diff)
    
    # Join all diffs and remove final trailing newline
    return "".join(file_diffs).rstrip("\n")


def validate_diff(diff_string: str, label: str) -> bool:
    """Validate that a diff string is parsable by unidiff."""
    if not diff_string:
        return True
    try:
        PatchSet(diff_string)
        return True
    except Exception as e:
        print(f"  ⚠️  Failed to parse {label}: {e}")
        return False


def main() -> None:
    print(f"Reading {INPUT_FILE} …")
    with INPUT_FILE.open("r", encoding="utf-8") as f:
        data: list[dict] = json.load(f)

    print(f"Processing {len(data)} entries …")
    failed_entries = []
    
    for i, entry in enumerate(data):
        patch_list = entry.pop("patch", None) or []
        test_patch_list = entry.pop("test_patch", None) or []

        # Preserve original per-file patch objects under new keys
        entry["patch_files"] = patch_list
        entry["test_patch_files"] = test_patch_list

        # Replace with standard unified diff strings
        patch_diff = patches_to_diff(patch_list) if patch_list else ""
        test_patch_diff = patches_to_diff(test_patch_list) if test_patch_list else ""
        
        # Validate both diffs
        instance_id = entry.get("instance_id", f"entry_{i}")
        valid_patch = validate_diff(patch_diff, f"{instance_id} patch")
        valid_test = validate_diff(test_patch_diff, f"{instance_id} test_patch")
        
        if not valid_patch or not valid_test:
            failed_entries.append(instance_id)
        
        entry["patch"] = patch_diff
        entry["test_patch"] = test_patch_diff

    if failed_entries:
        print(f"\n❌ {len(failed_entries)} entries failed validation:")
        for instance_id in failed_entries[:10]:
            print(f"   - {instance_id}")
        if len(failed_entries) > 10:
            print(f"   ... and {len(failed_entries) - 10} more")
        sys.exit(1)

    print(f"✓ All {len(data)} entries validated successfully")

    print(f"Writing {OUTPUT_FILE} …")
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("Done.")


if __name__ == "__main__":
    main()
