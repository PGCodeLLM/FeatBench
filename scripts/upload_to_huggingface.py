"""
Upload featbench_v1_0_standardized.json to Hugging Face as a dataset.

Repository: PGCodeLLM/FeatBench_v1.0
Split: test
"""

import json
from pathlib import Path
from datasets import Dataset
from huggingface_hub import HfApi

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = REPO_ROOT / "dataset" / "featbench_v1_0_standardized.json"
REPO_ID = "PGCodeLLM/FeatBench_v1.0"


def main():
    print(f"Loading {INPUT_FILE} ...")
    with INPUT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"Creating dataset from {len(data)} entries ...")
    dataset = Dataset.from_list(data)
    
    print(f"Uploading to {REPO_ID} (test split) ...")
    dataset.push_to_hub(
        REPO_ID,
        split="test",
        private=False,
    )
    
    print("✓ Upload complete!")
    print(f"View at: https://huggingface.co/datasets/{REPO_ID}")


if __name__ == "__main__":
    main()
