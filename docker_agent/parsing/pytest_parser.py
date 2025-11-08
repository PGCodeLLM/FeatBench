import re
from typing import Dict, List, Optional, Set
from enum import Enum
from collections import defaultdict


class TestStatus(Enum):
    """Test status enumeration"""
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class PytestResultParser:
    """
    Tool class for parsing pytest output results
    Supports parsing pytest -q -rA --tb=np format output
    """
    
    def __init__(self, output: str):
        """
        Initialize parser
        
        Args:
            output: pytest output string
        """
        self.output = output
        self.test_results: Dict[str, TestStatus] = {}
        self._parse_output()
    
    def _clean_ansi_codes(self, text: str) -> str:
        """Clean ANSI escape codes"""
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        return ansi_escape.sub('', text)
    
    def _parse_output(self):
        """Parse pytest output"""
        clean_output = self._clean_ansi_codes(self.output)
        
        summary_start = clean_output.find("short test summary info")
        if summary_start == -1:
            self._parse_from_full_output(clean_output)
            return
        
        summary_section = clean_output[summary_start:]
        
        lines = summary_section.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            self._parse_test_line(line)
    
    def _parse_from_full_output(self, clean_output: str):
        """Parse test results from full output (when no summary section)"""
        lines = clean_output.split('\n')
        for line in lines:
            line = line.strip()
            if any(status.value in line for status in TestStatus):
                self._parse_test_line(line)
    
    def _parse_test_line(self, line: str):
        """Parse single line test result"""
        # Match format: STATUS test_file.py::TestClass::test_method[params] - error_message
        # Or: STATUS test_file.py::test_function
        pattern = r'^(PASSED|FAILED|SKIPPED|ERROR)\s+(.+?)(?:\s-\s.*)?$'
        
        match = re.match(pattern, line)
        if match:
            status_str = match.group(1)
            test_path = match.group(2).strip()
            
            try:
                status = TestStatus(status_str)
                self.test_results[test_path] = status
            except ValueError:
                self.test_results[test_path] = TestStatus.UNKNOWN
    
    def _get_base_test_name(self, test_path: str) -> str:
        """
        Get base test name (remove parametrized part)
        
        Args:
            test_path: Complete test path
            
        Returns:
            Base test name
        """
        base_name = test_path.split('[')[0] if '[' in test_path else test_path
        return base_name
    
    def _aggregate_parametrized_results(self, test_results: Dict[str, TestStatus]) -> TestStatus:
        """
        Aggregate parametrized test results
        Rules:
        - If all results are passed or contain skipped (at least one passed) return passed
        - If any failed, errored, unknown, return failed
        
        Args:
            test_results: All parametrized results for same base test name
            
        Returns:
            Aggregated test status
        """
        if not test_results:
            return TestStatus.UNKNOWN
        
        statuses = list(test_results.values())
        
        if any(status in [TestStatus.FAILED, TestStatus.ERROR, TestStatus.UNKNOWN] for status in statuses):
            return TestStatus.FAILED
        
        if all(status in [TestStatus.PASSED, TestStatus.SKIPPED] for status in statuses):
            if any(status == TestStatus.PASSED for status in statuses):
                return TestStatus.PASSED
            else:
                return TestStatus.SKIPPED
        
        return TestStatus.UNKNOWN
    
    def get_test_status(self, test_pattern: str) -> Optional[TestStatus]:
        """
        Get status of specified test
        For parametrized tests, automatically aggregates all parameter results
        
        Args:
            test_pattern: Test pattern, like "test_api_jws.py::TestJWS::test_encode_with_jwk"
        
        Returns:
            Test status enum, returns None if not found
        """
        if test_pattern in self.test_results:
            return self.test_results[test_pattern]
        
        base_name = self._get_base_test_name(test_pattern)
        parametrized_results = {}
        
        for test_path, status in self.test_results.items():
            if self._get_base_test_name(test_path) == base_name:
                parametrized_results[test_path] = status
        
        if parametrized_results:
            return self._aggregate_parametrized_results(parametrized_results)
        
        return None
    
    def query_tests(self, test_patterns: List[str]) -> Dict[str, TestStatus]:
        """
        Query status of multiple tests
        
        Args:
            test_patterns: Test pattern list
        
        Returns:
            Mapping dict from test pattern to status
        """
        results = {}
        for pattern in test_patterns:
            status = self.get_test_status(pattern)
            results[pattern] = status if status else TestStatus.UNKNOWN
        return results
    
    def filter_tests_by_status(self, expected_statuses: Optional[List[TestStatus]] = None) -> Set[str]:
        """
        Filter test items that match expected status (aggregated parametrized results).

        Args:
            expected_statuses: Expected status list (e.g. [TestStatus.PASSED])

        Returns:
            Set of base test paths that match and have aggregated status in expected_statuses
        """
        if expected_statuses is None or not expected_statuses:
            expected_statuses = [TestStatus.PASSED]

        matched: Set[str] = set()
        base_test_groups = defaultdict(dict)
        for test_path, status in self.test_results.items():
            base_name = self._get_base_test_name(test_path)
            base_test_groups[base_name][test_path] = status

        for base_name, group_results in base_test_groups.items():
            aggregated = self._aggregate_parametrized_results(group_results)
            if aggregated in expected_statuses:
                matched.add(base_name)

        return matched