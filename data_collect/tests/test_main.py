"""
Unit tests for main.py module.
"""
import pytest
import json
from unittest.mock import Mock, patch, mock_open
from pathlib import Path
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main
from main import (
    setup_output_directory,
    collect_repositories,
    analyze_releases,
    enhance_with_pr_analysis,
    save_final_results,
    print_sample_results
)


class TestSetupOutputDirectory:
    """Test setup_output_directory function"""

    def test_setup_output_directory(self):
        """Test creating output directory"""
        output_dir = Path('/tmp/test_output')

        with patch('main.OUTPUT_DIR', output_dir):
            setup_output_directory()

        assert output_dir.exists()


class TestCollectRepositories:
    """Test collect_repositories function"""

    def test_collect_repositories_success(self):
        """Test successful repository collection"""
        from release_collector import Repository, Release

        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository = Repository(
            full_name='test/repo',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        with patch('main.get_repositories_to_process') as mock_get_repos:
            mock_get_repos.return_value = ([], {})  # No new repos, no processed repos
            result = collect_repositories(use_cache=False)

            assert result == []

    def test_collect_repositories_with_processed(self):
        """Test collection with already processed repositories"""
        from release_collector import Repository, Release

        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository = Repository(
            full_name='test/repo',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        processed_repos = {'test/repo': repository}

        with patch('main.get_repositories_to_process') as mock_get_repos:
            mock_get_repos.return_value = ([], processed_repos)
            result = collect_repositories(use_cache=False)

            assert len(result) == 1
            assert result[0].full_name == 'test/repo'

    def test_collect_repositories_no_repos_pass_filter(self):
        """Test when no repositories pass filtering"""
        with patch('main.get_repositories_to_process') as mock_get_repos:
            mock_get_repos.return_value = ([], {})  # No new repos, no processed repos
            result = collect_repositories(use_cache=False)

            assert result == []

    def test_collect_repositories_with_new_repos(self):
        """Test collection with new repositories to process"""
        from release_collector import Repository, Release

        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository = Repository(
            full_name='test/repo2',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        new_repos = [
            {
                'full_name': 'test/repo2',
                'stargazers_count': 1000,
                'size': 10000,
                'topics': ['python'],
                'releases_data': []
            }
        ]

        with patch('main.get_repositories_to_process') as mock_get_repos:
            with patch('main.process_single_repository', return_value=repository):
                mock_get_repos.return_value = (new_repos, {})
                result = collect_repositories(use_cache=False)

                assert len(result) == 1
                assert result[0].full_name == 'test/repo2'

    def test_collect_repositories_with_processing_error(self):
        """Test handling errors during repository processing"""
        new_repos = [
            {
                'full_name': 'test/repo',
                'stargazers_count': 1000,
                'size': 10000,
                'topics': ['python'],
                'releases_data': []
            }
        ]

        with patch('main.get_repositories_to_process') as mock_get_repos:
            with patch('main.process_single_repository', side_effect=Exception('Processing error')):
                mock_get_repos.return_value = (new_repos, {})
                result = collect_repositories(use_cache=False)

                # Should return empty list when error occurs
                assert result == []


class TestAnalyzeReleases:
    """Test analyze_releases function"""

    def test_analyze_releases_success(self):
        """Test successful release analysis"""
        from release_collector import Repository, Release
        from release_analyzer import ReleaseAnalysis

        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository = Repository(
            full_name='test/repo',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        repositories = [repository]

        with patch('main.analyze_repository_releases') as mock_analyze:
            mock_analyze.return_value = [
                ReleaseAnalysis(
                    tag_name='v1.0.0',
                    repo_name='test/repo',
                    new_features=[],
                    improvements=[],
                    bug_fixes=[],
                    other_changes=[],
                    processed_body='Release notes',
                    analyzed_at='2024-01-01'
                )
            ]

            result = analyze_releases(repositories)

            assert len(result) == 1
            assert result[0].tag_name == 'v1.0.0'

    def test_analyze_releases_multiple_repos(self):
        """Test analysis of multiple repositories"""
        from release_collector import Repository, Release
        from release_analyzer import ReleaseAnalysis

        release1 = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        release2 = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository1 = Repository(
            full_name='test/repo1',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release1],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        repository2 = Repository(
            full_name='test/repo2',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release2],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        repositories = [repository1, repository2]

        with patch('main.analyze_repository_releases') as mock_analyze:
            mock_analyze.side_effect = [
                [ReleaseAnalysis(
                    tag_name='v1.0.0',
                    repo_name='test/repo1',
                    new_features=[],
                    improvements=[],
                    bug_fixes=[],
                    other_changes=[],
                    processed_body='Release notes',
                    analyzed_at='2024-01-01'
                )],
                [ReleaseAnalysis(
                    tag_name='v1.0.0',
                    repo_name='test/repo2',
                    new_features=[],
                    improvements=[],
                    bug_fixes=[],
                    other_changes=[],
                    processed_body='Release notes',
                    analyzed_at='2024-01-01'
                )]
            ]

            result = analyze_releases(repositories)

            assert len(result) == 2
            assert result[0].repo_name == 'test/repo1'
            assert result[1].repo_name == 'test/repo2'


class TestEnhanceWithPRAnalysis:
    """Test enhance_with_pr_analysis function"""

    def test_enhance_with_pr_analysis_success(self):
        """Test successful PR enhancement"""
        from release_analyzer import ReleaseAnalysis, FeatureAnalysis

        feature = FeatureAnalysis(
            feature_type='new_feature',
            description='Test feature',
            pr_links=['https://github.com/test/repo/pull/123']
        )

        release_analysis = ReleaseAnalysis(
            tag_name='v1.0.0',
            repo_name='test/repo',
            new_features=[feature],
            improvements=[],
            bug_fixes=[],
            other_changes=[],
            processed_body='Release notes',
            analyzed_at='2024-01-01'
        )

        release_analyses = [release_analysis]

        with patch('main.enhance_release_analysis_with_pr_details') as mock_enhance:
            from pr_analyzer import EnhancedFeature

            mock_enhance.return_value = [
                EnhancedFeature(
                    feature_type='new_feature',
                    description='Test feature',
                    pr_analyses=[],
                    feature_detailed_description='Detailed description'
                )
            ]

            result = enhance_with_pr_analysis(release_analyses)

            assert len(result) == 1
            assert 'enhanced_new_features' in result[0]
            assert 'original_analysis' in result[0]

    def test_enhance_with_pr_analysis_no_features(self):
        """Test enhancement when no features to enhance"""
        from release_analyzer import ReleaseAnalysis

        release_analysis = ReleaseAnalysis(
            tag_name='v1.0.0',
            repo_name='test/repo',
            new_features=[],
            improvements=[],
            bug_fixes=[],
            other_changes=[],
            processed_body='Release notes',
            analyzed_at='2024-01-01'
        )

        release_analyses = [release_analysis]

        with patch('main.enhance_release_analysis_with_pr_details') as mock_enhance:
            mock_enhance.return_value = []  # No enhanced features

            result = enhance_with_pr_analysis(release_analyses)

            assert len(result) == 0


class TestSaveFinalResults:
    """Test save_final_results function"""

    def test_save_final_results_success(self):
        """Test successful saving of final results"""
        enhanced_results = [
            {
                'repository': 'test/repo',
                'release': 'v1.0.0',
                'analyzed_at': '2024-01-01',
                'enhanced_new_features': [],
                'original_analysis': {}
            }
        ]

        output_file = Path('/tmp/final_results.json')

        with patch('main.FINAL_RESULTS_FILE', output_file):
                with patch('builtins.open', mock_open()) as mock_file:
                    with patch('json.dump') as mock_json:
                        save_final_results(enhanced_results)

                        # Verify json.dump was called with correct data
                        assert mock_json.called
                        call_args = mock_json.call_args[0]
                        assert 'metadata' in call_args[0]
                        assert 'results' in call_args[0]
                        assert call_args[0]['metadata']['total_repositories'] == 1
                        assert call_args[0]['metadata']['total_releases'] == 1

    def test_save_final_results_with_enhanced_features(self):
        """Test saving results with enhanced features"""
        enhanced_results = [
            {
                'repository': 'test/repo1',
                'release': 'v1.0.0',
                'analyzed_at': '2024-01-01',
                'enhanced_new_features': [
                    {
                        'feature_type': 'new_feature',
                        'description': 'Feature 1',
                        'pr_analyses': [],
                        'feature_detailed_description': 'Detailed description'
                    }
                ],
                'original_analysis': {}
            },
            {
                'repository': 'test/repo2',
                'release': 'v2.0.0',
                'analyzed_at': '2024-01-02',
                'enhanced_new_features': [],
                'original_analysis': {}
            }
        ]

        output_file = Path('/tmp/final_results.json')

        with patch('main.FINAL_RESULTS_FILE', output_file):
                with patch('builtins.open', mock_open()) as mock_file:
                    with patch('json.dump') as mock_json:
                        save_final_results(enhanced_results)

                        # Verify statistics
                        call_args = mock_json.call_args[0]
                        metadata = call_args[0]['metadata']
                        assert metadata['total_repositories'] == 2
                        assert metadata['total_releases'] == 2
                        assert metadata['total_enhanced_features'] == 1

    def test_save_final_results_file_error(self):
        """Test handling file writing errors"""
        enhanced_results = [
            {
                'repository': 'test/repo',
                'release': 'v1.0.0',
                'analyzed_at': '2024-01-01',
                'enhanced_new_features': [],
                'original_analysis': {}
            }
        ]

        output_file = Path('/tmp/final_results.json')

        with patch('main.FINAL_RESULTS_FILE', output_file):
                with patch('builtins.open', side_effect=IOError('Write error')):
                    # Should handle error gracefully (just print warning)
                    save_final_results(enhanced_results)


class TestPrintSampleResults:
    """Test print_sample_results function"""

    def test_print_sample_results(self, capsys):
        """Test printing sample results"""
        enhanced_results = [
            {
                'repository': 'test/repo',
                'release': 'v1.0.0',
                'enhanced_new_features': [
                    {
                        'description': 'Feature A - a comprehensive feature for testing',
                        'pr_analyses': [
                            {
                                'pr_number': '123',
                                'title': 'Add feature A',
                                'detailed_description': 'I want to add a comprehensive feature that does X and Y.'
                            }
                        ],
                        'feature_detailed_description': 'I want to implement a feature that provides A and B capabilities.'
                    }
                ]
            }
        ]

        print_sample_results(enhanced_results)

        captured = capsys.readouterr()
        assert 'Sample 1' in captured.out
        assert 'test/repo' in captured.out
        assert 'v1.0.0' in captured.out

    def test_print_sample_results_empty(self, capsys):
        """Test printing when no results"""
        enhanced_results = []

        print_sample_results(enhanced_results)

        captured = capsys.readouterr()
        # Should print only the header
        assert 'Sample Results Preview' in captured.out

    def test_print_sample_results_limit(self, capsys):
        """Test limiting number of sample results printed"""
        enhanced_results = [
            {
                'repository': f'test/repo{i}',
                'release': f'v{i}.0.0',
                'enhanced_new_features': []
            }
            for i in range(10)
        ]

        print_sample_results(enhanced_results)

        captured = capsys.readouterr()
        # Should only print 3 samples despite having 10 results
        assert 'Sample 1' in captured.out
        assert 'Sample 2' in captured.out
        assert 'Sample 3' in captured.out
        assert 'Sample 4' not in captured.out


class TestMainFunction:
    """Test main function and argument parsing"""

    @patch('main.setup_output_directory')
    @patch('main.collect_repositories')
    @patch('main.analyze_releases')
    @patch('main.enhance_with_pr_analysis')
    @patch('main.save_final_results')
    @patch('main.print_sample_results')
    def test_main_full_pipeline(self, mock_print, mock_save, mock_enhance, mock_analyze, mock_collect, mock_setup):
        """Test full pipeline execution"""
        from release_collector import Repository, Release
        from release_analyzer import ReleaseAnalysis

        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository = Repository(
            full_name='test/repo',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        release_analysis = ReleaseAnalysis(
            tag_name='v1.0.0',
            repo_name='test/repo',
            new_features=[],
            improvements=[],
            bug_fixes=[],
            other_changes=[],
            processed_body='Release notes',
            analyzed_at='2024-01-01'
        )

        enhanced_results = [
            {
                'repository': 'test/repo',
                'release': 'v1.0.0',
                'analyzed_at': '2024-01-01',
                'enhanced_new_features': [],
                'original_analysis': {}
            }
        ]

        with patch('sys.argv', ['main.py']):
            mock_collect.return_value = [repository]
            mock_analyze.return_value = [release_analysis]
            mock_enhance.return_value = enhanced_results

            # Run main
            with patch('time.strftime', return_value='2024-01-01'):
                main.main()

            mock_setup.assert_called_once()
            mock_collect.assert_called_once()
            mock_analyze.assert_called_once()
            mock_enhance.assert_called_once()
            mock_save.assert_called_once()
            mock_print.assert_called_once()

    @patch('main.setup_output_directory')
    @patch('main.collect_repositories')
    def test_main_collect_only(self, mock_collect, mock_setup):
        """Test main with --collect-only flag"""
        from release_collector import Repository, Release

        release = Release(
            tag_name='v1.0.0',
            name='Release 1.0',
            body='Release notes',
            published_at='2024-01-01T00:00:00Z',
            target_commitish='main',
            version_tuple=(1, 0, 0),
            version_key='1.0.0'
        )

        repository = Repository(
            full_name='test/repo',
            stargazers_count=1000,
            size=10000,
            topics=['python'],
            releases_count=1,
            major_releases=[release],
            readme_content='Test',
            ci_configs={},
            processed_at='2024-01-01'
        )

        with patch('sys.argv', ['main.py', '--collect-only']):
            mock_collect.return_value = [repository]

            main.main()

            mock_setup.assert_called_once()
            mock_collect.assert_called_once()

    def test_main_no_cache_flag(self):
        """Test main with --no-cache flag"""
        with patch('main.setup_output_directory'):
            with patch('main.collect_repositories', return_value=[]):
                with patch('sys.argv', ['main.py', '--no-cache']):
                    # Should exit gracefully when no repos (returns without error)
                    main.main()

    def test_main_keyboard_interrupt(self):
        """Test handling KeyboardInterrupt"""
        with patch('main.setup_output_directory'):
            with patch('main.collect_repositories', side_effect=KeyboardInterrupt()):
                with patch('sys.argv', ['main.py']):
                    with pytest.raises(SystemExit) as exc_info:
                        main.main()

                    assert exc_info.value.code == 1

    def test_main_exception(self):
        """Test handling general exceptions"""
        with patch('main.setup_output_directory'):
            with patch('main.collect_repositories', side_effect=Exception('Unexpected error')):
                with patch('sys.argv', ['main.py']):
                    with pytest.raises(SystemExit) as exc_info:
                        main.main()

                    assert exc_info.value.code == 1
