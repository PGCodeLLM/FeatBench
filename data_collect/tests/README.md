# Tests for data_collect Module

This directory contains comprehensive unit tests for the `data_collect` module of the FeatBench project.

## Test Structure

```
tests/
├── __init__.py              # Package initialization
├── conftest.py             # Pytest configuration and shared fixtures
├── pytest.ini             # Pytest settings
├── run_tests.sh           # Test runner script
├── README.md              # This file
├── test_utils.py          # Tests for utils.py
├── test_release_collector.py  # Tests for release_collector.py
├── test_release_analyzer.py   # Tests for release_analyzer.py
├── test_pr_analyzer.py        # Tests for pr_analyzer.py
└── test_main.py               # Tests for main.py
```

## Running Tests

### Prerequisites

Make sure you have the required dependencies installed:

```bash
pip install pytest pytest-cov
```

### Running All Tests

From the `data_collect` directory, run:

```bash
# Using the test runner script
./tests/run_tests.sh

# Or directly with pytest
python -m pytest tests/ -v

# With coverage report
python -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
```

### Running Specific Test Files

```bash
# Test a specific module
python -m pytest tests/test_utils.py -v

# Test a specific test class
python -m pytest tests/test_utils.py::TestIsTestFile -v

# Test a specific test method
python -m pytest tests/test_utils.py::TestIsTestFile::test_test_file_patterns -v
```

### Running Tests with Filtering

```bash
# Run only fast tests (exclude slow tests)
python -m pytest -m "not slow"

# Run only unit tests
python -m pytest -m unit

# Run tests with "version" in the name
python -m pytest -k version -v
```

## Test Coverage

The test suite aims to achieve high code coverage:

- **utils.py**: Data classes, utility functions, GitHub API wrappers
- **release_collector.py**: Repository collection, filtering, caching
- **release_analyzer.py**: Release analysis with LLM integration
- **pr_analyzer.py**: PR analysis, code change detection, LLM enhancement
- **main.py**: Main orchestration logic, CLI argument handling

### Generating Coverage Report

```bash
# Generate HTML coverage report
python -m pytest tests/ --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Test Features

### Mocking and Fixtures

The test suite uses extensive mocking to:
- Avoid external API calls (GitHub, OpenAI)
- Simulate network responses
- Test error handling scenarios
- Provide consistent test data

### Shared Fixtures (conftest.py)

Common test data and configurations:
- `mock_config`: Mock configuration dictionary
- `mock_github_response`: Mock GitHub API responses
- `mock_openai_response`: Mock OpenAI API responses
- `sample_repository`: Sample Repository object
- `sample_pr_files`: Sample PR file changes
- `sample_release_analysis`: Sample ReleaseAnalysis object

### Test Categories

1. **Unit Tests**: Test individual functions and methods
2. **Integration Tests**: Test component interactions (marked with `@pytest.mark.integration`)
3. **API Tests**: Tests that make API calls (marked with `@pytest.mark.api`)

## Key Test Areas

### utils.py Tests

- `TestIsTestFile`: Test file identification logic
- `TestExtractVersionComponents`: Version number parsing with various formats
- `TestExtractPRNumberFromURL`: URL parsing for PR numbers
- `TestDataClasses`: Serialization/deserialization of data classes
- `TestGitHubAPIFunctions`: GitHub API wrapper functions

### release_collector.py Tests

- `TestLoadConfig`: Configuration loading
- `TestIsValidRelease`: Release validation logic
- `TestFilterByMetadataAndReleases`: Repository filtering
- `TestGetMajorReleases`: Version grouping logic
- `TestProcessSingleRepository`: Repository processing workflow
- `TestCacheManagement`: Cache loading and saving

### release_analyzer.py Tests

- `TestFeatureAnalysis` & `TestReleaseAnalysis`: Data class tests
- `TestAnalysisCache`: Cache management
- `TestAnalyzeReleaseWithLLM`: LLM integration
- `TestAnalyzeRelease`: Release analysis workflow
- `TestAnalyzeRepositoryReleases`: Multi-release analysis

### pr_analyzer.py Tests

- `TestExtractDefinitions`: AST parsing for Python code
- `TestAnalyzeFunctionChanges`: Function addition/deletion detection
- `TestPRAnalysisCache`: PR analysis caching
- `TestDataClasses`: PRAnalysis and EnhancedFeature classes
- `TestGenerateDetailedDescriptionWithLLM`: LLM description generation
- `TestAnalyzePR`: PR analysis workflow
- `TestEnhanceFeatureWithPRAnalysis`: Feature enhancement

### main.py Tests

- `TestLoadConfig`: Configuration loading
- `TestSetupOutputDirectory`: Output directory creation
- `TestCollectRepositories`: Repository collection workflow
- `TestAnalyzeReleases`: Release analysis orchestration
- `TestEnhanceWithPRAnalysis`: PR enhancement workflow
- `TestSaveFinalResults`: Result saving
- `TestPrintSampleResults`: Sample result display
- `TestMainFunction`: CLI argument handling and full pipeline

## Mocking External Services

### GitHub API

All GitHub API calls are mocked to:
- Return controlled test data
- Simulate error conditions (404, 403, etc.)
- Test rate limiting scenarios
- Avoid actual network requests

### OpenAI API

OpenAI API calls are mocked to:
- Return predefined analysis results
- Test prompt construction
- Simulate API errors
- Avoid incurring API costs

### File System

File system operations are mocked to:
- Test cache loading/saving
- Simulate file existence scenarios
- Test error handling for file operations

## Adding New Tests

### Test Naming Convention

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<functionality>`

### Best Practices

1. Use descriptive test names that explain what is being tested
2. Group related tests in test classes
3. Use fixtures for common test data
4. Mock external dependencies
5. Test both success and failure scenarios
6. Include docstrings for complex tests
7. Use parametrization for multiple test cases

### Example Test

```python
def test_my_function_success(mock_fixture):
    """Test successful execution of my_function"""
    # Arrange
    input_data = "test input"
    expected_output = "expected result"

    # Act
    result = my_function(input_data)

    # Assert
    assert result == expected_output

def test_my_function_error(mock_fixture):
    """Test error handling in my_function"""
    # Arrange
    invalid_input = None

    # Act & Assert
    with pytest.raises(ValueError):
        my_function(invalid_input)
```

## Continuous Integration

The test suite is designed to run in CI/CD environments:
- All tests are isolated and don't require external services
- Tests run in parallel for faster execution
- Coverage reports can be generated automatically
- Exit codes properly indicate test success/failure

## Troubleshooting

### Common Issues

1. **Import Errors**: Make sure you're running tests from the correct directory
2. **Mock Issues**: Check that all external dependencies are properly mocked
3. **File Path Issues**: Use `Path(__file__).parent` for relative paths
4. **Fixture Issues**: Ensure fixtures are properly defined in `conftest.py`

### Debugging Tests

```bash
# Run tests with verbose output
python -m pytest tests/test_module.py -v -s

# Drop into debugger on failure
python -m pytest tests/test_module.py --pdb

# Capture print statements
python -m pytest tests/test_module.py -s
```

## Performance Considerations

- Tests run in isolation without external API calls
- Mock sleeps are used to speed up test execution
- Fixtures are cached by pytest for efficiency
- Tests can run in parallel with `pytest-xdist`:

```bash
# Run tests in parallel
pip install pytest-xdist
python -m pytest tests/ -n auto
```

## Maintenance

When modifying code:
1. Update existing tests to match new behavior
2. Add tests for new functionality
3. Remove tests for deprecated features
4. Ensure coverage remains high
5. Update this README if needed
