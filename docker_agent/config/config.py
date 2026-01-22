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

# Experiment suffix
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
model_name = AGENTS[0].model.replace('/', '_').replace('\\', '_').replace(':', '_')
EXP_SUFFIX = f"{timestamp}_{model_name}"

# Logging configuration
LOGGING_LEVEL = config.level
LOGGING_FORMAT = config.format
LOG_FILE = current_dir / config.log_file
new_filename = f"{LOG_FILE.stem}_{EXP_SUFFIX}{LOG_FILE.suffix}"
LOG_FILE = LOG_FILE.parent / new_filename

# Path configuration
ANALYSIS_FILE = current_dir / config.analysis_file
# AGENTLESS_FILE = current_dir / config.agentless_file if config.agentless_file else None

# Execution configuration
MAX_SPECS_PER_REPO = config.max_specs_per_repo
DEFAULT_PYTHON_VERSION = config.default_python_version
MAX_EVAL_WORKERS = config.max_eval_workers

# File names
SETUP_FILES_NAME = config.setup_files_list
RECOMMENDED_PYTHON_VERSION = config.recommended_python_version
EVALUATION_RESULTS_FILE = current_dir / config.evaluation_results_file

# Trae configuration
TRAE_TIMESTAMP_FORMAT = config.trajectory_timestamp_format

# Proxy configuration
PROXY_ENABLED = config.proxy_enabled
PROXY_HTTP = config.proxy_http
PROXY_HTTPS = config.proxy_https

# Docker configuration
DOCKER_TIMEOUT = config.docker_timeout

# Prompt templates
PROMPTS = config.PROMPTS

# Get terminal size and define environment variables
terminal_size = shutil.get_terminal_size()
terminal_width = terminal_size.columns
terminal_height = terminal_size.lines

DOCKER_ENVIRONMENT = {
    "COLUMNS": str(terminal_width),
    "LINES": str(terminal_height),
    "HF_HUB_OFFLINE": "1"
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