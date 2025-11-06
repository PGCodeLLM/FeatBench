# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FeatBench is an end-to-end benchmark pipeline that transforms real GitHub feature releases into executable evaluation tasks for software agents. It measures how well agents implement feature-level changes using natural-language prompts.

**Key Components:**
- **data_collect/**: GitHub mining and release/PR analysis pipeline
- **docker_agent/**: Docker-based execution, patch application, and scoring
- **data/**: Processed evaluation outputs and results

Environment has been configured with conda, always activate `codegen` before you want to use `bash` to execuate any commands.

## Architecture

### Data Collection Pipeline (data_collect/)

The data collection system operates in 4 stages:

1. **Repository Collection** (`release_collector.py`): Mines GitHub for candidate repositories based on stars, release count, and topic filters
2. **Release Analysis** (`release_analyzer.py`): Analyzes releases to identify new features and improvements
3. **PR Enhancement** (`pr_analyzer.py`): Enriches releases with PR-level diffs and LLM-authored task descriptions using DeepSeek Chat API
4. **Output Generation** (`main.py`): Orchestrates all stages and produces `final_analysis_results.json`

**Key Classes/Functions:**
- `Repository` class: Stores repository metadata
- `get_repositories_to_process()`: Filters repositories based on criteria in `config.toml`
- `analyze_repository_releases()`: Core release analysis logic
- `enhance_release_analysis_with_pr_details()`: PR-level analysis with LLM summarization

**Configuration:** `data_collect/config.toml`
- GitHub API token and OpenAI-compatible API credentials
- Crawl mode (stars/specified) and filtering thresholds
- Cache files for rate limiting and performance

### Docker Agent System (docker_agent/)

The evaluation system runs agents in isolated Docker containers:

1. **Dataset Transformation** (`dataset_transformation.py`): Converts `final_analysis_results.json` into agent-facing JSON with repository-grouped patches
2. **Environment Preparation** (`run.py` + `docker_setup.py`):
   - `DockerEnvironmentManager`: Manages container lifecycle and caching
   - `AgentManager`: Handles trae-agent setup and file discovery
   - Creates per-repository container images with dependencies
3. **Agent Execution** (`evaluate.py` + `agent_executor.py`):
   - `AgentExecutor`: Runs agents (trae-agent, agentless) via Docker or locally
   - Applies historical test patches
   - Executes FAIL_TO_PASS and PASS_TO_PASS pytest selections
4. **Test Analysis** (`locate_test.py`, `patch_analyzer.py`):
   - `CodeChangeAnalyzer`: Identifies relevant test files
   - `PytestFilter`: Generates targeted test selections
   - `PatchAnalyzer`: Applies and validates patches

**Key Classes:**
- `DockerAgentRunner`: Main orchestrator with signal handling for clean shutdown
- `AgentEvaluator`: Handles agent configuration and execution flow
- `ContainerOperator`: Manages individual container operations
- `CacheManager`: Caches container images to speed up retries

**Configuration:** `docker_agent/config.toml`
- Agent configurations (models, providers, install commands)
- Proxy settings and Docker timeouts
- Prompt templates for environment setup and file discovery
- Logging configuration

## Configuration Files

**data_collect/config.toml:**
- `github_token`: GitHub PAT with `repo` and `read:org` permissions
- `openai_api_key`, `openai_base_url`, `openai_model`: LLM provider credentials
- `release_collector`: Star thresholds, release counts, excluded topics
- `crawl_mode`: "stars" for star-ranked repos or "specified" for curated list
- Output path: `swebench-live/final_analysis_results.json`

**docker_agent/config.toml:**
- `proxy.enabled`: Set to `true` if behind proxy (auto-populated by environment)
- `docker.timeout`: Container operation timeout in seconds
- `paths.analysis_file`: Path to dataset JSON from transformation step
- `execution.max_specs_per_repo`: Limit specs per repository
- Agent definitions: Name, repo URL, branch, model, provider, install commands

## Output Artifacts

- `data/processed_evaluation_results_*.json`: Curated evaluation summaries (30-50MB files)
- `docker_agent/logs/test_logs.json`: Detailed pytest logs before/after patch application
- `docker_agent/swap/`: Transient working directory (can be safely deleted)
- `docker_agent/logs/*.log`: Execution logs for debugging
- `swebench-live/`: Intermediate caches and raw analysis results

## Important Implementation Details

### GitHub API Rate Limiting
- The data collection stage makes extensive API calls
- Cache files prevent duplicate requests: `processed_repos_cache.json`, `release_analysis_cache.json`, `pr_analysis_cache.json`
- Adjust sleep intervals in `pr_analyzer.py` if hitting secondary limits

### Docker Configuration
- **GPU Support**: NVIDIA runtime enabled by default (remove `device_requests` for CPU-only)
- **Image Caching**: Each repository gets a cached container image for faster retries
- **Signal Handling**: Clean container shutdown on Ctrl+C via `signal.signal()`

### Test Execution Strategy
- Tests use `pytest-timeout` (5s default) and `pytest-xdist` (parallel)
- `FAIL_TO_PASS`: Tests that should pass after applying the patch
- `PASS_TO_PASS`: Tests that should continue passing (regression check)
- Always use `--tb=short` to avoid excessive tracebacks

### Patch Application
- `PatchAnalyzer` validates patch applicability before execution
- Test patches are applied before agent runs
- Source patches generated by agents are applied after execution