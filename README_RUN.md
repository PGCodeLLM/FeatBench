# FeatBench

## Overview

FeatBench is a comprehensive benchmark for evaluating AI agents on real-world software development tasks.

## Getting Started

### 1. Installation

Clone this repo and install the requirements:

```bash
conda create -n FeatBench python=3.13 -y
conda activate FeatBench

pip install -r requirements.txt
pip install -e .
```

### 2. Cloning Repositories

FeatBench stores all the repositories inside `docker_agent/swap` and mounts this directory into the runtime containers. Running the following command will clone all repositories in the dataset.

```bash
python -m docker_agent.runner.main --agents trae-agent
```

The command will print errors, but it's normal, as long as the repositories are cloned. I had to modify the dataset file and make all the instances as `"processed": false` to force the benchmark to clone the repositories.

### 3. Dataset Loading Configuration

FeatBench supports loading datasets from two sources:

#### Option A: Local JSON File (Default)

Load from a local JSON file:

```toml
# In docker_agent/settings.toml
dataset_source = "json"
analysis_file = "../dataset/featbench_v1_0.json"
```

#### Option B: Hugging Face Dataset

Load from the Hugging Face dataset repository:

```toml
# In docker_agent/settings.toml
dataset_source = "hf"
hf_dataset_repo = "PGCodeLLM/FeatBench_v1.0"
hf_dataset_split = "test"
```

**Requirements**: To use Hugging Face datasets, ensure you have the `datasets` library installed:

```bash
pip install datasets
```

**Environment Variables**: You can also configure the dataset source using environment variables:

```bash
export DOCKER_AGENT_DATASET_SOURCE="hf"
export DOCKER_AGENT_HF_DATASET_REPO="PGCodeLLM/FeatBench_v1.0"
export DOCKER_AGENT_HF_DATASET_SPLIT="test"
```

### 4. Pulling Docker Images

Pull the Docker images for the benchmark:

```bash
python scripts/pull_images.py --dataset dataset/featbench_v1_0.json
```

### 5. Configuring LLM Settings

Configure your LLM provider settings:

First copy the example configuration:

```bash
cp docker_agent/swap/trae-agent/trae_config.yaml.example docker_agent/swap/trae-agent/trae_config.yaml
```

To use openrouter or self-hosted LLMs, add this to model_providers list:
```yaml
    openrouter:
        api_key: "api_key"
        provider: openrouter
        base_url: "http://example.com/v1"
```
Using `provider: openrouter` will use the completions endpoint, whereas using `provider: openai` will use the responses endpoint. Currently SGLang does not support custom tools ([https://github.com/sgl-project/sglang/issues/13292](https://github.com/sgl-project/sglang/issues/13292)).

Use the following configuration in `docker_agent/swap/trae-agent/trae_config.yaml` file:
```yaml
models:
    trae_agent_model:
        model_provider: openrouter
        model: "qwen3_coder_30b"
```

Also specify the model in `docker_agent/agents.toml`:
```yaml
# Agent Configurations
# This file contains configurations for different agents

[[agents]]
name = "trae-agent"
model = "qwen3_coder_30b"
provider = "openrouter"
repo_url = "https://github.com/PGCodeLLM/trae-agent.git"
branch = "main"
install_command = "uv sync --all-extras"
```

### 6. Running the Benchmark

Run the benchmark evaluation:

```bash
python -m docker_agent.runner.main --evaluate --agents trae-agent
```

Results are saved in `docker_agent/evaluation_results.json`
