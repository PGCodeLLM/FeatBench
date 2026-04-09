"""
Unified configuration module using Dynaconf

Supports multi-environment configuration:
- Default configuration: settings.toml
- Environment variable override: supports dynamic configuration changes via env vars
- Convenient access: directly access config via config.KEY
"""

from dynaconf import Dynaconf
from pathlib import Path
import os
import shutil
import sys
from datetime import datetime
import uuid

current_dir = Path(__file__).parent.parent

# Create Dynaconf instance
config = Dynaconf(
    settings_files=[
        current_dir / "settings.toml",
        current_dir / "agents.toml",
        current_dir / ".secrets.toml",  # Optional secrets file (not version controlled)
    ],
    environments=False,
    envvar_prefix="DOCKER_AGENT",
    validate_required=False,
    merge_enabled=True,
)

# Convenient exports for common configuration items
# Agent configurations
AGENTS = config.AGENTS

# Experiment UUID
EXP_UUID = str(uuid.uuid4())[:8]

# Experiment ID
# Allow resuming an experiment by supplying -t/--resume-timestamp on the CLI.
_resume_timestamp = None
for _i, _arg in enumerate(sys.argv):
    if _arg in ("-t", "--resume-timestamp") and _i + 1 < len(sys.argv):
        _resume_timestamp = sys.argv[_i + 1]
        break
timestamp = _resume_timestamp if _resume_timestamp else datetime.now().strftime("%Y%m%d-%H%M%S")
# EXP_ID embeds the model name of the agent being evaluated. Ideally we'd
# read this from the parsed argparse result, but config.py is executed at
# import time — before argparse runs in main.py. We therefore inspect sys.argv
# directly here to find the first value passed to --agents, look it up in
# AGENTS, and use its model name. If --agents is absent (e.g. runner mode) we
# fall back to the first agent defined in agents.toml.
_cli_agent_name = None
for _i, _arg in enumerate(sys.argv):
    if _arg == "--agents" and _i + 1 < len(sys.argv):
        _cli_agent_name = sys.argv[_i + 1]
        break
_selected_agent = next((a for a in AGENTS if a.name == _cli_agent_name), None) if _cli_agent_name else None
_model_for_id = (_selected_agent or AGENTS[0]).model
model_name = _model_for_id.replace('/', '_').replace('\\', '_').replace(':', '_')
EXP_ID = f"{timestamp}_{model_name}"

# Logging configuration
LOGGING_LEVEL = config.level
LOGGING_FORMAT = config.format
LOG_FILE = current_dir / config.log_file
new_filename = f"{LOG_FILE.stem}_{EXP_ID}{LOG_FILE.suffix}"
LOG_FILE = LOG_FILE.parent / new_filename

# Path configuration
ANALYSIS_FILE = current_dir / config.analysis_file

# Dataset source configuration
DATASET_SOURCE = config.get("dataset_source", "json")  # "json" or "hf"
HF_DATASET_REPO = config.get("hf_dataset_repo", "PGCodeLLM/FeatBench_v1.0")
HF_DATASET_SPLIT = config.get("hf_dataset_split", "test")

# AGENTLESS_FILE = current_dir / config.agentless_file if config.agentless_file else None

# Execution configuration
MAX_SPECS_PER_REPO = config.max_specs_per_repo
DEFAULT_PYTHON_VERSION = config.default_python_version
MAX_EVAL_WORKERS = config.max_eval_workers

# File names
SETUP_FILES_NAME = config.setup_files_list
RECOMMENDED_PYTHON_VERSION = config.recommended_python_version

# Directory containing per-experiment evaluation result files. Each run writes
# to EVALUATION_RESULTS_DIR / f"{EXP_ID}.json". Resolved relative to the repo
# root (one level above docker_agent/) so results sit at the project top level.
EVALUATION_RESULTS_DIR = current_dir.parent / config.evaluation_results_dir

# Trae configuration
TRAE_TIMESTAMP_FORMAT = config.trajectory_timestamp_format

# Proxy configuration
PROXY_ENABLED = config.proxy_enabled
PROXY_HTTP = config.proxy_http
PROXY_HTTPS = config.proxy_https

# Docker configuration
DOCKER_TIMEOUT = config.docker_timeout
RESOURCE_LIMITS_ENABLED = config.resource_limits_enabled

# Prompt templates
PROMPTS = config.PROMPTS

# Get terminal size and define environment variables
terminal_size = shutil.get_terminal_size()
terminal_width = terminal_size.columns
terminal_height = terminal_size.lines

DOCKER_ENVIRONMENT = {
    "COLUMNS": str(terminal_width),
    "LINES": str(terminal_height),
    "HF_HUB_OFFLINE": "1",
    # Disable ANSI color output from tools that respect these conventions
    # (pytest, rich, click, etc.) so exec.log stays human-readable.
    "NO_COLOR": "1",
    "PY_COLORS": "0",
    "TERM": "dumb",
}

# Preprocess Dockerfile template with proxy and user configurations
proxy_and_user_lines = []

# Add proxy configurations if enabled
if PROXY_ENABLED:
    if PROXY_HTTP:
        DOCKER_ENVIRONMENT["HTTP_PROXY"] = PROXY_HTTP
        DOCKER_ENVIRONMENT["http_proxy"] = PROXY_HTTP
        proxy_and_user_lines.append(f"ARG HTTP_PROXY={PROXY_HTTP}")
        proxy_and_user_lines.append(f"ARG http_proxy={PROXY_HTTP}")
    if PROXY_HTTPS:
        DOCKER_ENVIRONMENT["HTTPS_PROXY"] = PROXY_HTTPS
        DOCKER_ENVIRONMENT["https_proxy"] = PROXY_HTTPS
        proxy_and_user_lines.append(f"ARG HTTPS_PROXY={PROXY_HTTPS}")
        proxy_and_user_lines.append(f"ARG https_proxy={PROXY_HTTPS}")

proxy_and_user_lines.append(f"ENV HOST_UID={os.getuid()}")
proxy_and_user_lines.append(f"ENV HOST_GID={os.getgid()}")

proxy_and_user_args = "\n".join(proxy_and_user_lines) + "\n\n"

_base_template = config.DOCKERFILE.template
DOCKERFILE_TEMPLATE = _base_template.replace("{proxy_and_user_args}", proxy_and_user_args)