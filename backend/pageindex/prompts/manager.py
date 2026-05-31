"""Prompt Manager - Hot reloadable prompt templates"""

import json
import time
from pathlib import Path
from typing import Dict, Optional, Any
import yaml


class PromptManager:
    """Manages prompt templates with hot reload support"""

    def __init__(self, templates_dir: str = None):
        if templates_dir is None:
            # Default to pageindex/prompts/templates relative to this file
            current_dir = Path(__file__).parent
            self.templates_dir = current_dir / "templates"
        else:
            self.templates_dir = Path(templates_dir)

        self._cache: Dict[str, Dict] = {}  # Memory cache
        self._file_mtimes: Dict[str, float] = {}  # File modification times

    def get_prompt(self, doc_type: str) -> Dict[str, Any]:
        """Get prompt template with hot reload support"""
        # Check if file has been modified
        if self._is_file_modified(doc_type):
            return self._reload_template(doc_type)

        # Return from cache
        if doc_type in self._cache:
            return self._cache[doc_type]

        # Load from file
        return self._load_template(doc_type)

    def _is_file_modified(self, doc_type: str) -> bool:
        """Check if template file has been modified"""
        file_path = self._get_file_path(doc_type)
        if not file_path.exists():
            return False

        current_mtime = file_path.stat().st_mtime
        last_mtime = self._file_mtimes.get(doc_type, 0)
        return current_mtime > last_mtime

    def _reload_template(self, doc_type: str) -> Dict[str, Any]:
        """Reload template from file"""
        print(f"[PromptManager] Hot reloading {doc_type}")
        return self._load_template(doc_type)

    def _load_template(self, doc_type: str) -> Dict[str, Any]:
        """Load template from YAML file"""
        file_path = self._get_file_path(doc_type)

        # Fallback to general if specific template doesn't exist
        if not file_path.exists():
            print(f"[PromptManager] Template {doc_type} not found, using general")
            file_path = self._get_file_path("general")

        if not file_path.exists():
            raise FileNotFoundError(f"Neither {doc_type} nor general template found")

        with open(file_path, "r", encoding="utf-8") as f:
            template = yaml.safe_load(f)

        # Update cache
        self._cache[doc_type] = template
        self._file_mtimes[doc_type] = file_path.stat().st_mtime

        return template

    def _get_file_path(self, doc_type: str) -> Path:
        """Get file path for template"""
        return self.templates_dir / f"{doc_type}.yaml"

    def get_system_prompt(self, doc_type: str) -> str:
        """Get system prompt for document type"""
        template = self.get_prompt(doc_type)
        return template.get("template", {}).get("system", "")

    def get_examples(self, doc_type: str) -> list:
        """Get few-shot examples for document type"""
        template = self.get_prompt(doc_type)
        return template.get("template", {}).get("examples", [])

    def get_quality_checks(self, doc_type: str) -> Dict:
        """Get quality check configuration"""
        template = self.get_prompt(doc_type)
        return template.get("quality_checks", {})

    def clear_cache(self):
        """Clear memory cache"""
        self._cache.clear()
        self._file_mtimes.clear()
