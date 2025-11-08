"""Spec processing logic"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from docker_agent.core.types import TestStatus, CodeChange, Spec, Container
from docker_agent.container.container_operator import ContainerOperator
from docker_agent.parsing.change_analyzer import CodeChangeAnalyzer, PytestFilter


class SpecProcessor:
    """Processes evaluation specifications"""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.logger = logging.getLogger(__name__)

    def process(self, container: Container, spec: Spec):
        """Process a single evaluation spec"""

        operator = ContainerOperator(spec.repo_name, container)

        self._reset_and_apply(operator, spec.base_commit, [])
        test_code_before = self.get_test_code(spec, spec.repo_name)

        self._reset_and_apply(operator, spec.base_commit, [spec.test_patch])
        test_code_after = self.get_test_code(spec, spec.repo_name)

        test_func = self.get_test_func(test_code_before, test_code_after)
        if all(not changes for changes_dict in test_func for changes in changes_dict.values()):
            self.logger.info(f"Skipping test for spec {spec.instance_id}")
            spec.processed = True
            return

        self._reset_and_apply(operator, spec.base_commit, [spec.test_patch])
        f2p_failed, f2p_pre_logs = self._run_tests(operator, spec.repo_name, test_func, [TestStatus.FAILED, TestStatus.ERROR], False)

        self._reset_and_apply(operator, spec.base_commit, [spec.test_patch, spec.patch])
        f2p_passed, f2p_post_logs = self._run_tests(operator, spec.repo_name, test_func, [TestStatus.PASSED], False)

        self._reset_and_apply(operator, spec.base_commit, [spec.test_patch])
        p2p_pre_passed, p2p_pre_logs = self._run_tests(operator, spec.repo_name, None, [TestStatus.PASSED])

        self._reset_and_apply(operator, spec.base_commit, [spec.test_patch, spec.patch])
        p2p_post_passed, p2p_post_logs = self._run_tests(operator, spec.repo_name, None, [TestStatus.PASSED])

        self.logger.info(f"Test files that failed before patch: {sorted(f2p_failed)}")
        self.logger.info(f"Test files that passed before patch: {sorted(p2p_pre_passed)[:5]}")
        self.logger.info(f"Test files that passed after patch: {sorted(f2p_passed)}")
        self.logger.info(f"Test files that still passed after patch: {sorted(p2p_post_passed)[:5]}")

        fail_to_pass = f2p_failed & f2p_passed
        pass_to_pass = p2p_pre_passed & p2p_post_passed

        spec.FAIL_TO_PASS = ", ".join(sorted(fail_to_pass)) if fail_to_pass else None
        spec.PASS_TO_PASS = ", ".join(sorted(pass_to_pass)) if pass_to_pass else None
        spec.processed = True

        self.logger.info("=== Test Results Summary ===")
        self.logger.info(f"Tests that only passed after patch: {spec.FAIL_TO_PASS}")
        self.logger.info(f"Tests that passed both before and after patch: {spec.PASS_TO_PASS}")

    def get_test_code(self, spec: Spec, repo_name: str):
        """Get test code before and after patch"""
        test_py = []
        for f in spec.test_files:
            if f.endswith(".py"):
                try:
                    test_py.append(Path(self.base_path / "swap" / repo_name / f).read_text(encoding="utf-8", errors='replace'))
                except FileNotFoundError:
                    test_py.append("")

        file_names = [f for f in spec.test_files if f.endswith(".py")]
        return [{name: text} for name, text in zip(file_names, test_py)]

    def get_test_func(self, code_before: List[Dict[str, Any]], code_after: List[Dict[str, Any]]) -> List[Dict[str, CodeChange]]:
        """Get modified test functions"""
        analyzer = CodeChangeAnalyzer()
        pytest_filter = PytestFilter()
        result = []
        for before, after in zip(code_before, code_after):
            file_name = list(before.keys())[0]
            before_code = before[file_name]
            after_code = after[file_name]
            changes = analyzer.analyze_changes(before_code, after_code)
            pytest_changes = pytest_filter.filter_pytest_changes(changes)
            result.append({file_name: pytest_changes})
        return result

    def _run_tests(self, operator: ContainerOperator, repo_name: str, test_filter: Optional[List[Dict[str, CodeChange]]], expected_statuses: List[TestStatus], use_xdist: bool = True):
        """Run tests and return results"""
        if test_filter is None:
            passed, logs = operator.run_tests_in_container(repo_name, expected_statuses=expected_statuses, use_xdist=use_xdist)
        else:
            passed, logs = operator.run_tests_in_container(repo_name, test_filter, expected_statuses, use_xdist=use_xdist)
        return set(passed), logs

    def _reset_and_apply(self, operator: ContainerOperator, base_commit: str, patches: List[List[Dict[str, Any]]]):
        """Reset and apply patches"""
        operator.checkout_commit(base_commit, use_docker=True)
        for p in patches or []:
            if p:
                operator.apply_patches(p)