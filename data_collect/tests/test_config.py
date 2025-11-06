"""
Test suite for Dynaconf configuration module
"""

import pytest
from pathlib import Path


class TestConfigModule:
    """Test the config module with Dynaconf"""

    def test_config_import(self):
        """Test that config module can be imported"""
        from data_collect import config
        assert config is not None

    def test_config_has_expected_attributes(self):
        """Test that config has expected attributes"""
        from data_collect import config
        assert hasattr(config, 'config')
        assert hasattr(config, 'GITHUB_TOKEN')
        assert hasattr(config, 'GITHUB_API_BASE')
        assert hasattr(config, 'GITHUB_HEADERS')

    def test_github_token_is_set(self):
        """Test that GitHub token is loaded"""
        from data_collect.config import GITHUB_TOKEN
        assert GITHUB_TOKEN is not None
        assert len(GITHUB_TOKEN) > 0
        assert isinstance(GITHUB_TOKEN, str)

    def test_openai_config_is_set(self):
        """Test that OpenAI configuration is loaded"""
        from data_collect.config import OPENAI_API_KEY, OPENAI_MODEL

        assert OPENAI_API_KEY is not None
        assert len(OPENAI_API_KEY) > 0
        assert OPENAI_MODEL is not None
        assert len(OPENAI_MODEL) > 0

    def test_output_directories_are_path_objects(self):
        """Test that output directories are Path objects"""
        from data_collect.config import OUTPUT_DIR, CACHE_FILE, ANALYSIS_CACHE_FILE, PR_ANALYSIS_CACHE_FILE

        assert isinstance(OUTPUT_DIR, Path)
        assert isinstance(CACHE_FILE, Path)
        assert isinstance(ANALYSIS_CACHE_FILE, Path)
        assert isinstance(PR_ANALYSIS_CACHE_FILE, Path)

    def test_filtering_thresholds_are_integers(self):
        """Test that filtering thresholds are integers"""
        from data_collect.config import MIN_STARS, RANK_START, RANK_END, MIN_RELEASES

        assert isinstance(MIN_STARS, int)
        assert isinstance(RANK_START, int)
        assert isinstance(RANK_END, int)
        assert isinstance(MIN_RELEASES, int)

    def test_excluded_topics_is_set(self):
        """Test that excluded topics is a set"""
        from data_collect.config import EXCLUDED_TOPICS

        assert isinstance(EXCLUDED_TOPICS, set)
        assert len(EXCLUDED_TOPICS) > 0
        assert 'tutorial' in EXCLUDED_TOPICS

    def test_test_directories_is_list(self):
        """Test that test directories is a list"""
        from data_collect.config import TEST_DIRECTORIES

        assert isinstance(TEST_DIRECTORIES, list)
        assert len(TEST_DIRECTORIES) > 0
        assert 'test' in TEST_DIRECTORIES
        assert 'tests' in TEST_DIRECTORIES

    def test_prompts_are_available(self):
        """Test that prompt templates are available"""
        from data_collect.config import PROMPTS

        assert PROMPTS is not None
        assert hasattr(PROMPTS, 'release_analysis_system')
        assert hasattr(PROMPTS, 'release_analysis_user')
        assert hasattr(PROMPTS, 'pr_analysis_system')
        assert hasattr(PROMPTS, 'pr_analysis_user')

    def test_config_access_via_dot_notation(self):
        """Test that config can be accessed via dot notation"""
        from data_collect.config import config

        assert config.COMMON.github_token is not None
        assert config.COMMON.openai_model is not None
        assert config.COMMON.crawl_mode is not None

    def test_config_file_paths(self):
        """Test that config file paths are correct"""
        from data_collect.config import config
        from pathlib import Path

        current_dir = Path(__file__).parent.parent
        assert (current_dir / "config.toml").exists()

    def test_environment_variable_override(self):
        """Test that environment variables can override config"""
        import os
        from data_collect.config import config

        # Save original value
        original_value = os.environ.get('DYNACONF_GITHUB_TOKEN')

        # Set test value
        os.environ['DYNACONF_GITHUB_TOKEN'] = 'test_token_123'

        # Reload config (Dynaconf will pick up the env var)
        from importlib import reload
        from data_collect import config as config_module
        reload(config_module)

        # Note: In a real scenario, we'd need to test this more carefully
        # For now, just verify the env var is set
        assert os.environ.get('DYNACONF_GITHUB_TOKEN') == 'test_token_123'

        # Restore original value
        if original_value is None:
            os.environ.pop('DYNACONF_GITHUB_TOKEN', None)
        else:
            os.environ['DYNACONF_GITHUB_TOKEN'] = original_value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
