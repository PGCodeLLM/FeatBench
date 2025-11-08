import ast
import textwrap
import logging
from typing import Dict, List, Set, Optional
from docker_agent.core.types import CodeChange

class PytestFilter:
    """Pytest test filter - filter out pytest-related test methods and functions"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def is_pytest_function(self, func_name: str) -> bool:
        """Determine if it is a pytest test function"""
        return func_name.startswith('test_')
    
    def is_pytest_class(self, class_name: str) -> bool:
        """Determine if it is a pytest test class"""
        return class_name.startswith('Test')
    
    def is_pytest_method(self, method_name: str) -> bool:
        """Determine if it is a pytest test method (format: TestClass.test_method)"""
        if '.' not in method_name:
            return False
        
        class_name, method = method_name.split('.', 1)
        return self.is_pytest_class(class_name) and self.is_pytest_function(method)
    
    def filter_pytest_changes(self, changes: List[CodeChange]) -> List[CodeChange]:
        """Filter out pytest-related code changes"""
        pytest_changes = []
        
        for change in changes:
            if change.code_type == 'function' and self.is_pytest_function(change.name):
                pytest_changes.append(change)
            elif change.code_type == 'method' and self.is_pytest_method(change.name):
                pytest_changes.append(change)
        
        return pytest_changes

class CodeChangeAnalyzer:
    """Code change analyzer"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_python_code(self, code_content: str) -> Dict[str, Set[str]]:
        """Parse Python code, extract all classes, functions and methods"""
        try:
            tree = ast.parse(code_content)
            result = {
                'classes': set(),
                'functions': set(),
                'methods': set()
            }
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    result['classes'].add(node.name)
                    
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            result['methods'].add(f"{node.name}.{item.name}")
                
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parent_classes = [n for n in ast.walk(tree) 
                                    if isinstance(n, ast.ClassDef) and node in ast.walk(n)]
                    if not parent_classes:
                        result['functions'].add(node.name)
            
            return result
            
        except SyntaxError as e:
            self.logger.info(f"Syntax error, cannot parse code: {e}")
            return {'classes': set(), 'functions': set(), 'methods': set()}
    
    def analyze_changes(self, code_before: str, code_after: str) -> List[CodeChange]:
        """Analyze changes between two versions of code"""
        changes = []
        
        self.logger.info("Analyzing code changes...")
        
        before_elements = self.parse_python_code(code_before)
        after_elements = self.parse_python_code(code_after)
        
        self.logger.info(f"Before change: {len(before_elements['functions'])} functions, "
              f"{len(before_elements['classes'])} classes, "
              f"{len(before_elements['methods'])} methods")
        self.logger.info(f"After change: {len(after_elements['functions'])} functions, "
              f"{len(after_elements['classes'])} classes, "
              f"{len(after_elements['methods'])} methods")
        
        for code_type in ['classes', 'functions', 'methods']:
            before_set = before_elements[code_type]
            after_set = after_elements[code_type]
            
            added = after_set - before_set
            for name in added:
                changes.append(CodeChange(name, 'added', code_type.rstrip('s')))
            
            deleted = before_set - after_set
            for name in deleted:
                changes.append(CodeChange(name, 'deleted', code_type.rstrip('s')))
        
        modified_elements = self.find_modified_elements(code_before, code_after, before_elements, after_elements)
        for element_name, element_type in modified_elements:
            # Avoid duplicating elements already marked as added or deleted
            existing_names = [c.name for c in changes]
            if element_name not in existing_names:
                changes.append(CodeChange(element_name, 'modified', element_type))
        
        return changes
    
    def find_modified_elements(self, code_before: str, code_after: str, 
                             before_elements: Dict, after_elements: Dict) -> List[tuple]:
        """Find modified elements (content changed but name unchanged)"""
        modified = []
        
        common_functions = before_elements['functions'] & after_elements['functions']
        for func_name in common_functions:
            if self.is_function_modified(func_name, code_before, code_after):
                modified.append((func_name, 'function'))
        
        common_classes = before_elements['classes'] & after_elements['classes']
        for class_name in common_classes:
            if self.is_class_modified(class_name, code_before, code_after):
                modified.append((class_name, 'class'))
        
        common_methods = before_elements['methods'] & after_elements['methods']
        for method_name in common_methods:
            if self.is_method_modified(method_name, code_before, code_after):
                modified.append((method_name, 'method'))
        
        return modified
    
    def extract_code_lines(self, code: str, start_line: int, end_line: int) -> str:
        """Safely extract code lines and handle indentation"""
        lines = code.split('\n')
        if start_line < 0 or end_line > len(lines):
            return ""
        
        extracted_lines = lines[start_line:end_line]
        if not extracted_lines:
            return ""
        
        # Use textwrap.dedent to remove common indentation
        extracted_code = '\n'.join(extracted_lines)
        normalized_code = textwrap.dedent(extracted_code)
        
        return normalized_code
    
    def get_function_info(self, func_name: str, code: str, in_class: str = None) -> Optional[tuple]:
        """Get function line number info (start_line, end_line)"""
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == func_name:
                        if in_class:
                            for class_node in ast.walk(tree):
                                if (isinstance(class_node, ast.ClassDef) and 
                                    class_node.name == in_class and 
                                    node in ast.walk(class_node)):
                                    return (node.lineno - 1, node.end_lineno)
                        else:
                            in_any_class = False
                            for class_node in ast.walk(tree):
                                if (isinstance(class_node, ast.ClassDef) and 
                                    node in ast.walk(class_node)):
                                    in_any_class = True
                                    break
                            
                            if not in_any_class:
                                return (node.lineno - 1, node.end_lineno)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting function {func_name} info: {e}")
            return None
    
    def get_class_info(self, class_name: str, code: str) -> Optional[tuple]:
        """Get class line number info (start_line, end_line)"""
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return (node.lineno - 1, node.end_lineno)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting class {class_name} info: {e}")
            return None
    
    def is_function_modified(self, func_name: str, code_before: str, code_after: str) -> bool:
        """Check if function is modified"""
        try:
            info_before = self.get_function_info(func_name, code_before)
            info_after = self.get_function_info(func_name, code_after)
            
            if not info_before or not info_after:
                return False
            
            func_before = self.extract_code_lines(code_before, info_before[0], info_before[1])
            func_after = self.extract_code_lines(code_after, info_after[0], info_after[1])
            
            if not func_before or not func_after:
                return False
            
            func_before_normalized = self.normalize_code(func_before)
            func_after_normalized = self.normalize_code(func_after)
            
            is_modified = func_before_normalized != func_after_normalized
            
            if is_modified:
                self.logger.info(f"Function {func_name} is modified")
            
            return is_modified
            
        except Exception as e:
            self.logger.error(f"Error checking function {func_name} modification status: {e}")
            return False
    
    def is_class_modified(self, class_name: str, code_before: str, code_after: str) -> bool:
        """Check if class is modified"""
        try:
            info_before = self.get_class_info(class_name, code_before)
            info_after = self.get_class_info(class_name, code_after)
            
            if not info_before or not info_after:
                return False
            
            class_before = self.extract_code_lines(code_before, info_before[0], info_before[1])
            class_after = self.extract_code_lines(code_after, info_after[0], info_after[1])
            
            if not class_before or not class_after:
                return False
            
            class_before_normalized = self.normalize_code(class_before)
            class_after_normalized = self.normalize_code(class_after)
            
            is_modified = class_before_normalized != class_after_normalized
            
            if is_modified:
                self.logger.info(f"Class {class_name} is modified")
            
            return is_modified
            
        except Exception as e:
            self.logger.error(f"Error checking class {class_name} modification status: {e}")
            return False
    
    def is_method_modified(self, method_name: str, code_before: str, code_after: str) -> bool:
        """Check if method is modified"""
        if '.' not in method_name:
            return False
        
        try:
            class_name, method = method_name.split('.', 1)
            
            info_before = self.get_function_info(method, code_before, in_class=class_name)
            info_after = self.get_function_info(method, code_after, in_class=class_name)
            
            if not info_before or not info_after:
                return False
            
            method_before = self.extract_code_lines(code_before, info_before[0], info_before[1])
            method_after = self.extract_code_lines(code_after, info_after[0], info_after[1])
            
            if not method_before or not method_after:
                return False
            
            method_before_normalized = self.normalize_code(method_before)
            method_after_normalized = self.normalize_code(method_after)
            
            is_modified = method_before_normalized != method_after_normalized
            
            if is_modified:
                self.logger.info(f"Method {method_name} is modified")
            
            return is_modified
            
        except Exception as e:
            self.logger.error(f"Error checking method {method_name} modification status: {e}")
            return False
    
    def normalize_code(self, code: str) -> str:
        """Normalize code for comparison"""
        lines = []
        for line in code.split('\n'):
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        
        return '\n'.join(lines)