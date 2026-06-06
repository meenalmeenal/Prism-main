import json
import yaml
import logging
from typing import Dict, List, Any
from src.utils.pii_masker import mask_pii

logger = logging.getLogger(__name__)

class SpecCollector:
    """Collects and parses OpenAPI/Swagger specs as test case input."""

    def process_spec_file(self, file_path: str) -> Dict:
        """Read an OpenAPI/Swagger JSON or YAML file and extract endpoints."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.endswith('.json'):
                    spec = json.load(f)
                else:
                    spec = yaml.safe_load(f)

            return self._extract_from_spec(spec, source=file_path)

        except Exception as e:
            raise Exception(f"Failed to process spec file: {str(e)}")

    def process_spec_url(self, url: str) -> Dict:
        """Fetch an OpenAPI spec from a URL."""
        try:
            import requests
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            if 'yaml' in res.headers.get('Content-Type', ''):
                spec = yaml.safe_load(res.text)
            else:
                spec = res.json()
            return self._extract_from_spec(spec, source=url)
        except Exception as e:
            raise Exception(f"Failed to fetch spec from URL: {str(e)}")

    def _extract_from_spec(self, spec: Dict, source: str) -> Dict:
        """Extract endpoints and build acceptance criteria from OpenAPI spec."""
        title = spec.get('info', {}).get('title', 'API Spec')
        version = spec.get('info', {}).get('version', '1.0')
        paths = spec.get('paths', {})

        endpoints = []
        acceptance_criteria = []

        for path, methods in paths.items():
            for method, details in methods.items():
                if method.lower() not in ['get', 'post', 'put', 'patch', 'delete']:
                    continue

                summary = details.get('summary', f'{method.upper()} {path}')
                responses = list(details.get('responses', {}).keys())
                params = [p.get('name') for p in details.get('parameters', [])]

                endpoint = {
                    "path": path,
                    "method": method.upper(),
                    "summary": summary,
                    "responses": responses,
                    "parameters": params
                }
                endpoints.append(endpoint)

                # Generate ACs from endpoint
                ac = f"{method.upper()} {path}: {summary}"
                acceptance_criteria.append(mask_pii(ac))

                for status in responses:
                    if str(status).startswith('2'):
                        acceptance_criteria.append(
                            f"{method.upper()} {path} returns {status} on success"
                        )
                    elif str(status).startswith('4'):
                        acceptance_criteria.append(
                            f"{method.upper()} {path} returns {status} on invalid input"
                        )

        logger.info("Extracted %d endpoints from spec: %s", len(endpoints), title)

        return {
            "source": "api_spec",
            "issue_key": f"SPEC-{title[:10].replace(' ', '-').upper()}",
            "title": mask_pii(title),
            "description": f"API spec: {title} v{version}",
            "acceptance_criteria": acceptance_criteria,
            "metadata": {
                "source_file": source,
                "title": title,
                "version": version,
                "endpoint_count": len(endpoints),
                "endpoints": endpoints
            }
        }