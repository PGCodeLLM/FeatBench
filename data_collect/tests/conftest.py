"""
Pytest configuration and shared fixtures for data_collect tests.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import Repository, Release, Commit, FileChange


@pytest.fixture
def mock_github_response():
    """Mock GitHub API response"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    return mock_response


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response"""
    mock_response = Mock()
    mock_choice = Mock()
    mock_message = Mock()
    mock_message.content = '''
    {
        "new_features": [
            {
                "description": "Test feature",
                "pr_ids": ["123"]
            }
        ],
        "improvements": [],
        "bug_fixes": [],
        "other_changes": []
    }
    '''
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.fixture
def sample_repository():
    """Create a sample Repository object for testing"""
    releases = [
        Release(
            tag_name='v1.0.0',
            name='Release 1.0.0',
            body='Initial release',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )
    ]

    return Repository(
        full_name='test/repo',
        stargazers_count=1000,
        size=10000,
        topics=['python', 'testing'],
        releases_count=1,
        major_releases=releases,
        readme_content='# Test Repository\nThis is a test.',
        ci_configs={},
        processed_at='2024-01-01 00:00:00'
    )


@pytest.fixture
def sample_pr_files():
    """Create sample PR file changes"""
    return [
        FileChange(
            filename='src/module.py',
            status='modified',
            additions=10,
            deletions=2,
            changes=12,
            patch='@@ -10,7 +10,15 @@\n-def old_function():\n+def new_function():'
        ),
        FileChange(
            filename='tests/test_module.py',
            status='added',
            additions=20,
            deletions=0,
            changes=20,
            patch='@@ -0,0 +1,20 @@\n+def test_new_function():'
        )
    ]


@pytest.fixture
def sample_release_analysis():
    """Create a sample ReleaseAnalysis object"""
    from release_analyzer import FeatureAnalysis, ReleaseAnalysis

    feature = FeatureAnalysis(
        feature_type='new_feature',
        description='Test feature description',
        pr_links=['https://github.com/test/repo/pull/123']
    )

    return ReleaseAnalysis(
        tag_name='v1.0.0',
        repo_name='test/repo',
        new_features=[feature],
        improvements=[],
        bug_fixes=[],
        other_changes=[],
        processed_body='Initial release',
        analyzed_at='2024-01-01 00:00:00'
    )


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for GitHub API calls"""
    with patch('requests.get') as mock_get:
        yield mock_get


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client"""
    with patch('openai.OpenAI') as mock_client:
        mock_instance = Mock()
        mock_client.return_value = mock_instance

        mock_chat = Mock()
        mock_instance.chat = mock_chat

        mock_completions = Mock()
        mock_chat.completions = mock_completions

        yield mock_completions


@pytest.fixture
def mock_time_sleep():
    """Mock time.sleep to speed up tests"""
    with patch('time.sleep'):
        yield


# Parametrized test data for version extraction
VERSION_TEST_CASES = [
    # (tag_name, expected_version_tuple)
    ('v1.2.3', (1, 2, 3)),
    ('1.2.3', (1, 2, 3)),
    ('v1.0', (1, 0)),
    ('release-1.2.3', (1, 2, 3)),
    ('version.2.0.1', (2, 0, 1)),
    ('v 1.2.3', (1, 2, 3)),
    ('1.2.3.4.5', (1, 2, 3, 4, 5)),
    ('invalid-tag', None),
    ('v1.2.3-alpha', (1, 2, 3)),
    ('v1.2.3-beta.1', (1, 2, 3)),
]


@pytest.fixture(params=VERSION_TEST_CASES)
def version_test_case(request):
    """Parameterized fixture for version extraction tests"""
    return request.param


# Test file patterns
TEST_FILE_PATTERNS = [
    ('src/test_module.py', True),
    ('tests/test_foo.py', True),
    ('test_bar.py', True),
    ('conftest.py', True),
    ('src/module.py', False),
    ('README.md', False),
]
