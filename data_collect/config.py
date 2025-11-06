"""
Unified configuration module using Dynaconf

Supports multi-environment configuration:
- Default configuration: config.toml
- Environment variable override: supports dynamic configuration changes via env vars
- Convenient access: directly access config via config.KEY
"""

from dynaconf import Dynaconf
from pathlib import Path

# Get current directory
current_dir = Path(__file__).parent

# Create Dynaconf instance
# Supports loading from multiple files with environment variable override
config = Dynaconf(
    # List of configuration files (ordered by priority)
    settings_files=[
        current_dir / "config.toml",
        current_dir / ".secrets.toml",  # Optional secrets file (not version controlled)
    ],
    environments=False,
    envvar_prefix="FEATBENCH",
    validate_required=False,
    merge_enabled=True,
)

# Convenient exports for common configuration items
# GitHub API configuration
GITHUB_TOKEN = config.COMMON.github_token
GITHUB_API_BASE = config.COMMON.github_api_base
GITHUB_HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# OpenAI API configuration
OPENAI_API_KEY = config.COMMON.openai_api_key
OPENAI_MODEL = config.COMMON.openai_model
OPENAI_BASE_URL = config.COMMON.openai_base_url

# Crawling mode configuration
CRAWL_MODE = config.COMMON.crawl_mode
CRAWL_JSON_FILE = Path(current_dir) / config.COMMON.crawl_json_file

# Filtering thresholds
MIN_STARS = config.RELEASE_COLLECTOR.min_stars_range
RANK_START = config.RELEASE_COLLECTOR.rank_start
RANK_END = config.RELEASE_COLLECTOR.rank_end
MIN_RELEASES = config.RELEASE_COLLECTOR.min_releases
MIN_RELEASE_BODY_LENGTH = config.RELEASE_COLLECTOR.min_release_body_length
MIN_RELEASE_DATE = config.RELEASE_COLLECTOR.min_release_date
EXCLUDED_TOPICS = set(config.RELEASE_COLLECTOR.excluded_topics)

# Test case related configuration
TEST_DIRECTORIES = config.RELEASE_COLLECTOR.test_directories
TEST_FILE_PATTERNS = config.RELEASE_COLLECTOR.test_file_patterns
BOT_USERS = set(config.RELEASE_COLLECTOR.bot_users)

# Output and cache file paths
OUTPUT_DIR = Path(current_dir) / config.COMMON.output_dir
CACHE_FILE = OUTPUT_DIR / config.RELEASE_COLLECTOR.cache_file
ANALYSIS_CACHE_FILE = OUTPUT_DIR / config.RELEASE_ANALYZER.analysis_cache_file
PR_ANALYSIS_CACHE_FILE = OUTPUT_DIR / config.PR_ANALYZER.pr_analysis_cache_file

# README processing configuration
MAX_README_LENGTH = config.RELEASE_ANALYZER.max_readme_length
README_TRUNCATION_SUFFIX = config.RELEASE_ANALYZER.readme_truncation_suffix

# File change summary configuration
MAX_FILES_IN_SUMMARY = config.PR_ANALYZER.max_files_in_summary
MAX_PATCH_LENGTH = config.PR_ANALYZER.max_patch_length
MAX_PATCH_PREVIEW_LENGTH = config.PR_ANALYZER.max_patch_preview_length

# Main configuration
DEFAULT_RELEASE_LIMIT = config.RELEASE_COLLECTOR.default_release_limit
FINAL_RESULTS_FILE = OUTPUT_DIR / config.MAIN.final_results_file
SAMPLE_RESULTS_LIMIT = config.MAIN.sample_results_limit

# Prompt templates
PROMPTS = config.PROMPTS
