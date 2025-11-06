"""
Unit tests for utils.py module.
"""
import pytest
from unittest.mock import Mock, patch
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import (
    is_test_file,
    extract_version_components,
    extract_pr_number_from_url,
    get_pr_info,
    get_pr_files,
    get_file_content,
    get_commit_info,
    Repository,
    Release,
    FileChange,
    Commit
)


class TestIsTestFile:
    """Test is_test_file function"""

    def test_test_file_in_test_directory(self):
        """Test files in test directories with matching patterns are identified correctly"""
        # Files in test directories with matching patterns
        assert is_test_file('test/test_module.py') == True
        assert is_test_file('tests/test_foo.py') == True
        assert is_test_file('src/test/test_bar.py') == True
        assert is_test_file('path/to/test/test_something.py') == True
        assert is_test_file('tests/foo_test.py') == True

    def test_test_file_in_test_directory_conftest(self):
        """Test conftest.py in test directories"""
        # conftest.py in test directories should match
        assert is_test_file('tests/conftest.py') == True
        assert is_test_file('test/conftest.py') == True

    def test_test_file_in_test_directory_non_matching_pattern(self):
        """Test files in test directories but without matching patterns"""
        # Files in test directory but don't match test patterns
        assert is_test_file('test/module.py') == False
        assert is_test_file('tests/helper.py') == False
        assert is_test_file('src/test/utils.py') == False
        assert is_test_file('test/module_helper.py') == False

    def test_files_outside_test_directories(self):
        """Test files outside test directories are not identified as test files"""
        # Files outside test directories, even with test-like names
        assert is_test_file('src/test_module.py') == False
        assert is_test_file('module_test.py') == False
        assert is_test_file('test_module.py') == False
        assert is_test_file('src/module.py') == False
        assert is_test_file('main.py') == False
        assert is_test_file('README.md') == False
        assert is_test_file('setup.py') == False


class TestExtractVersionComponents:
    """Test extract_version_components function"""

    def test_standard_version_formats(self):
        """Test standard version formats (v prefix, no prefix)"""
        assert extract_version_components('v1.2.3') == (1, 2, 3)
        assert extract_version_components('1.2.3') == (1, 2, 3)

    def test_prefix_versions(self):
        """Test versions with various prefixes"""
        assert extract_version_components('release-1.2.3') == (1, 2, 3)
        assert extract_version_components('version.2.0.1') == (2, 0, 1)
        assert extract_version_components('ver-1.0.0') == (1, 0, 0)
        assert extract_version_components('rel.2.1') == (2, 1)

    def test_version_with_spaces(self):
        """Test versions with spaces"""
        assert extract_version_components('v 1.2.3') == (1, 2, 3)
        assert extract_version_components('1. 2. 3') == (1, 2, 3)

    def test_major_minor_only(self):
        """Test major.minor versions"""
        assert extract_version_components('v1.0') == (1, 0)
        assert extract_version_components('1.2') == (1, 2)

    def test_multi_component_versions(self):
        """Test versions with more than 3 components"""
        assert extract_version_components('1.2.3.4.5') == (1, 2, 3, 4, 5)

    def test_invalid_versions(self):
        """Test invalid version strings"""
        assert extract_version_components('invalid-tag') is None
        assert extract_version_components('') is None
        assert extract_version_components('no-numbers-here') is None

    def test_prerelease_versions(self):
        """Test prerelease versions (alpha, beta, rc)"""
        # Should still extract the version number
        assert extract_version_components('v1.2.3-alpha') == (1, 2, 3)
        assert extract_version_components('v1.2.3-beta.1') == (1, 2, 3)
        assert extract_version_components('1.0-rc1') == (1, 0)

    def test_version_with_underscores_and_hyphens(self):
        """Test versions with underscores and hyphens"""
        assert extract_version_components('1-2-3') == (1, 2, 3)
        assert extract_version_components('1_2_3') == (1, 2, 3)
        assert extract_version_components('v1-2-3-beta') == (1, 2, 3)

    def test_version_in_middle_of_string(self):
        """Test extracting version from middle of string"""
        assert extract_version_components('release-1.2.3-final') == (1, 2, 3)
        assert extract_version_components('ver_1.2.3') == (1, 2, 3)


class TestExtractPRNumberFromURL:
    """Test extract_pr_number_from_url function"""

    def test_valid_pr_urls(self):
        """Test extracting PR numbers from valid URLs"""
        assert extract_pr_number_from_url('https://github.com/user/repo/pull/123') == '123'
        assert extract_pr_number_from_url('https://github.com/user/repo/pull/1') == '1'
        assert extract_pr_number_from_url('/pull/456') == '456'

    def test_invalid_pr_urls(self):
        """Test extracting PR numbers from invalid URLs"""
        assert extract_pr_number_from_url('https://github.com/user/repo') is None
        assert extract_pr_number_from_url('https://github.com/user/repo/issues/123') is None
        assert extract_pr_number_from_url('invalid-url') is None


class TestRepository:
    """Test Repository data class"""

    def test_repository_to_dict(self):
        """Test converting Repository to dictionary"""
        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0.0',
            body='Test release',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repo = Repository(
            full_name='test/repo',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={'workflow.yml': 'ABC123'},
            processed_at='2024-01-01'
        )

        repo_dict = repo.to_dict()
        assert repo_dict['full_name'] == 'test/repo'
        assert repo_dict['stargazers_count'] == 1000
        assert len(repo_dict['major_releases']) == 1
        assert repo_dict['major_releases'][0]['tag_name'] == 'v1.0.0'
        assert repo_dict['ci_configs']['workflow.yml'] == 'ABC123'
        assert repo_dict['major_releases'][0]['published_at'] == '2024-01-01T00:00:00Z'

    def test_repository_from_dict(self):
        """Test creating Repository from dictionary"""
        data = {
            'full_name': 'test/repo',
            'stargazers_count': 1000,
            'size': 10000,
            'topics': ['python'],
            'releases_count': 1,
            'major_releases': [{
                'tag_name': 'v1.0.0',
                'name': 'Release 1.0.0',
                'body': 'Test release',
                'published_at': '2024-01-01T00:00:00Z',
                'target_commitish': 'main',
                'version_tuple': (1, 0, 0),
                'version_key': '1.0.0'
            }],
            'readme_content': 'Test',
            'ci_configs': {'workflow.yml': 'ABC123'},
            'processed_at': '2024-01-01'
        }

        repo = Repository.from_dict(data)
        assert repo.full_name == 'test/repo'
        assert repo.stargazers_count == 1000
        assert len(repo.major_releases) == 1
        assert repo.major_releases[0].tag_name == 'v1.0.0'
        assert repo.ci_configs['workflow.yml'] == 'ABC123'
        assert repo.major_releases[0].published_at == '2024-01-01T00:00:00Z'


class TestRelease:
    """Test Release data class"""

    def test_release_to_dict(self):
        """Test converting Release to dictionary"""
        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0.0',
            body='Test release',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        release_dict = release.to_dict()
        assert release_dict['tag_name'] == 'v1.0.0'
        assert release_dict['version_key'] == '1.0.0'
        assert release_dict['published_at'] == '2024-01-01T00:00:00Z'
        assert release_dict['target_commitish'] == 'main'
        assert release_dict['version_tuple'] == (1, 0, 0)

    def test_release_from_dict(self):
        """Test creating Release from dictionary"""
        data = {
            'tag_name': 'v1.0.0',
            'name': 'Release 1.0.0',
            'body': 'Test release',
            'published_at': '2024-01-01T00:00:00Z',
            'target_commitish': 'main',
            'version_tuple': (1, 0, 0),
            'version_key': '1.0.0'
        }

        release = Release.from_dict(data)
        assert release.tag_name == 'v1.0.0'
        assert release.version_key == '1.0.0'
        assert release.published_at == '2024-01-01T00:00:00Z'
        assert release.target_commitish == 'main'
        assert release.version_tuple == (1, 0, 0)


class TestFileChange:
    """Test FileChange data class"""

    def test_file_change_creation(self):
        """Test creating FileChange object"""
        file_change = FileChange(
            filename='src/module.py',
            status='modified',
            additions=10,
            deletions=2,
            changes=12,
            patch='test patch'
        )

        assert file_change.filename == 'src/module.py'
        assert file_change.status == 'modified'
        assert file_change.additions == 10
        assert file_change.deletions == 2
        assert file_change.changes == 12
        assert file_change.patch == 'test patch'

    def test_file_change_to_dict(self):
        """Test converting FileChange to dictionary"""
        file_change = FileChange(
            filename='src/module.py',
            status='modified',
            additions=10,
            deletions=2,
            changes=12,
            patch='test patch'
        )

        file_dict = file_change.to_dict()
        assert file_dict['filename'] == 'src/module.py'
        assert file_dict['status'] == 'modified'
        assert file_dict['additions'] == 10
        assert file_dict['deletions'] == 2
        assert file_dict['changes'] == 12
        assert file_dict['patch'] == 'test patch'

    def test_file_change_from_dict(self):
        """Test creating FileChange from dictionary"""
        data = {
            'filename': 'src/module.py',
            'status': 'modified',
            'additions': 10,
            'deletions': 2,
            'changes': 12
        }

        file_change = FileChange.from_dict(data)
        assert file_change.filename == 'src/module.py'
        assert file_change.status == 'modified'
        assert file_change.additions == 10
        assert file_change.deletions == 2
        assert file_change.changes == 12


class TestCommit:
    """Test Commit data class"""

    def test_commit_creation(self):
        """Test creating Commit object"""
        commit = Commit(
            sha='abc123',
            message='Test commit',
            date='2024-01-01T00:00:00Z',
            author='Test User'
        )

        assert commit.sha == 'abc123'
        assert commit.message == 'Test commit'
        assert commit.date == '2024-01-01T00:00:00Z'
        assert commit.author == 'Test User'

    def test_commit_to_dict(self):
        """Test converting Commit to dictionary"""
        commit = Commit(
            sha='abc123',
            message='Test commit',
            date='2024-01-01T00:00:00Z',
            author='Test User'
        )

        commit_dict = commit.to_dict()
        assert commit_dict['sha'] == 'abc123'

    def test_commit_from_dict(self):
        """Test creating Commit from dictionary"""
        data = {
            'sha': 'abc123',
            'message': 'Test commit',
            'date': '2024-01-01T00:00:00Z',
            'author': 'Test User'
        }

        commit = Commit.from_dict(data)
        assert commit.sha == 'abc123'
        assert commit.message == 'Test commit'
        assert commit.date == '2024-01-01T00:00:00Z'
        assert commit.author == 'Test User'


class TestGitHubAPIFunctions:
    """Test GitHub API functions"""

    @pytest.mark.parametrize('repo_name,pr_number,expected_url', [
        ('test/repo', '123', 'https://api.github.com/repos/test/repo/pulls/123'),
        ('user/A-project', '456', 'https://api.github.com/repos/user/A-project/pulls/456'),
    ])
    def test_get_pr_info_url_format(self, repo_name, pr_number, expected_url):
        """Test that PR info request is made to correct URL"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'number': 123,
                'title': 'Test PR',
                'state': 'closed'
            }
            mock_get.return_value = mock_response

            result = get_pr_info(repo_name, pr_number)

            # Verify the function was called and returned a value
            assert result is not None
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[0][0] == expected_url

    def test_get_pr_info_success(self, mock_requests_get):
        """Test successful PR info retrieval"""
        mock_requests_get.return_value.status_code = 200
        mock_requests_get.return_value.json.return_value = {
            'number': 123,
            'title': 'Test PR',
            'state': 'closed',
            'merged': True
        }

        result = get_pr_info('test/repo', '123')

        assert result is not None
        assert result['number'] == 123
        assert result['title'] == 'Test PR'

    def test_get_pr_info_not_found(self, mock_requests_get):
        """Test PR not found (404)"""
        mock_requests_get.return_value.status_code = 404

        result = get_pr_info('test/repo', '999')

        assert result is None

    def test_get_pr_files_success(self, mock_requests_get):
        """Test successful PR files retrieval"""
        mock_requests_get.return_value.status_code = 200
        mock_requests_get.return_value.json.return_value = [
            {
                'filename': 'src/module.py',
                'status': 'modified',
                'additions': 10,
                'deletions': 2,
                'changes': 12
            }
        ]

        result = get_pr_files('test/repo', '123')

        assert len(result) == 1
        assert result[0].filename == 'src/module.py'
        assert result[0].status == 'modified'

    def test_get_file_content_success(self, mock_requests_get):
        """Test successful file content retrieval"""
        import base64

        test_content = 'print("Hello, World!")\n'
        encoded_content = base64.b64encode(test_content.encode('utf-8')).decode()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'content': encoded_content
        }
        mock_requests_get.return_value = mock_response

        result = get_file_content('test/repo', 'src/module.py', 'abc123')

        assert result == test_content

    def test_get_commit_info_success(self, mock_requests_get):
        """Test successful commit info retrieval"""
        mock_requests_get.return_value.status_code = 200
        mock_requests_get.return_value.json.return_value = {
            'sha': 'abc123',
            'commit': {
                'message': 'Test commit',
                'author': {
                    'date': '2024-01-01T00:00:00Z',
                    'name': 'Test User'
                }
            }
        }

        result = get_commit_info('test/repo', 'abc123')

        assert result is not None
        assert result.sha == 'abc123'
        assert result.message == 'Test commit'
        assert result.author == 'Test User'

    def test_get_commit_info_not_found(self, mock_requests_get):
        """Test commit not found"""
        mock_requests_get.return_value.status_code = 404

        result = get_commit_info('test/repo', 'invalid')

        assert result is None
