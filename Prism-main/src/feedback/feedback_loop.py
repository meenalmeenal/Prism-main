"""
Feedback Loop for Test Regeneration

This module implements a feedback loop that analyzes test execution results
and triggers regeneration of failed tests using AI.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from ..ai_engine.ai_test_generator import AITestGenerator
from ..integrations.zephyr_client import ZephyrClient

logger = logging.getLogger(__name__)

class FeedbackLoop:
    """Handles feedback from test execution and triggers test regeneration."""

    def __init__(self, zephyr_client: Optional[ZephyrClient] = None, max_retries: int = 2):
        """Initialize the feedback loop.
        
        Args:
            zephyr_client: Zephyr client for updating test cases
            max_retries: Maximum number of regeneration attempts for failed tests
        """
        self.zephyr_client = zephyr_client
        self.max_retries = max_retries
        self.ai_generator = AITestGenerator()

    def analyze_execution_results(self, results_path: str) -> List[Dict[str, Any]]:
        """Analyze Playwright test execution results.
        
        Args:
            results_path: Path to Playwright test results JSON file
            
        Returns:
            List of failed test cases with failure details
        """
        failed_tests = []
        
        try:
            with open(results_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
                
            for suite in results.get('suites', []):
                for test in suite.get('specs', []):
                    for test_case in test.get('tests', []):
                        if test_case.get('status') in ('failed', 'timedOut'):
                            failed_test = {
                                'title': test_case.get('title'),
                                'file': test.get('file'),
                                'error': test_case.get('error', {}).get('message', 'Unknown error'),
                                'steps': test_case.get('results', [{}])[0].get('steps', []),
                                'retry_count': self._get_retry_count(test_case.get('title', ''))
                            }
                            failed_tests.append(failed_test)
                            
        except Exception as e:
            logger.error(f"Error analyzing test results: {str(e)}")
            
        return failed_tests

    def _get_retry_count(self, test_title: str) -> int:
        """Get the number of times a test has been retried.
        
        Args:
            test_title: Test title with possible -Rn suffix
            
        Returns:
            Current retry count (0 for first attempt)
        """
        match = re.search(r'-R(\d+)$', test_title)
        return int(match.group(1)) if match else 0

    def generate_retry_prompt(self, failed_test: Dict[str, Any]) -> str:
        """Generate a prompt for regenerating a failed test.
        
        Args:
            failed_test: Details of the failed test
            
        Returns:
            Prompt string for the AI
        """
        return f"""
        The following test case failed with the error: {failed_test['error']}
        
        Failed test details:
        Title: {failed_test['title']}
        File: {failed_test['file']}
        
        Test steps:
        {json.dumps(failed_test['steps'], indent=2)}
        
        Please analyze why this test might have failed and regenerate an improved version.
        Consider:
        1. Adding more specific selectors
        2. Adding waiting conditions
        3. Improving error handling
        4. Adding more assertions
        5. Fixing any timing issues
        
        Return the regenerated test case in the same format as the original.
        """

    async def regenerate_failed_tests(self, failed_tests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Regenerate failed tests using AI.
        
        Args:
            failed_tests: List of failed test cases
            
        Returns:
            List of regenerated test cases
        """
        regenerated_tests = []
        
        for test in failed_tests:
            if test['retry_count'] >= self.max_retries:
                logger.warning(f"Max retries reached for test: {test['title']}")
                continue
                
            prompt = self.generate_retry_prompt(test)
            try:
                # Generate new test case using AI
                new_test = await self.ai_generator.generate_test_case(prompt)
                
                # Update test ID with retry suffix
                base_id = re.sub(r'-R\d+$', '', test.get('test_id', ''))
                new_test['test_id'] = f"{base_id}-R{test['retry_count'] + 1}"
                new_test['regenerated_from'] = test.get('test_id')
                
                regenerated_tests.append(new_test)
                
                # Update Zephyr if connected
                if self.zephyr_client:
                    await self.zephyr_client.update_test_case(
                        test_id=test.get('test_id'),
                        updates={'status': 'FAILED', 'comment': f"Regenerated as {new_test['test_id']}"}
                    )
                    
            except Exception as e:
                logger.error(f"Error regenerating test {test.get('test_id')}: {str(e)}")
                
        return regenerated_tests

    async def process_execution_results(self, results_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process test execution results and regenerate failed tests.
        
        Args:
            results_path: Path to Playwright test results
            
        Returns:
            Tuple of (failed_tests, regenerated_tests)
        """
        # Analyze results
        failed_tests = self.analyze_execution_results(results_path)
        
        if not failed_tests:
            return [], []
            
        # Regenerate failed tests
        regenerated_tests = await self.regenerate_failed_tests(failed_tests)
        
        return failed_tests, regenerated_tests
