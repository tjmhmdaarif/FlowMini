"""
snippets.py — Voice Snippets System for FlowMini.

Voice snippets are voice-triggered shortcuts that paste full formatted text.
Supports variables/placeholders, formatting preservation, and hierarchical organization.
"""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any


@dataclass
class Snippet:
    """A voice snippet with trigger phrase and content."""
    name: str
    trigger: str              # Voice phrase to trigger this snippet
    content: str              # Text to insert (can contain placeholders)
    description: str = ""
    category: str = "general"  # Organize snippets into categories
    variables: Dict[str, str] = field(default_factory=dict)  # Default variable values
    tags: List[str] = field(default_factory=list)
    enabled: bool = True


class SnippetManager:
    """Manages voice snippets - loading, saving, matching, and expanding."""

    def __init__(self, snippets_path: str):
        self.snippets_path = snippets_path
        self.snippets: Dict[str, Snippet] = {}
        self._load()

    def _load(self):
        """Load snippets from JSON file."""
        if not os.path.exists(self.snippets_path):
            self._create_default_snippets()
            return

        try:
            with open(self.snippets_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data.get("snippets", []):
                snippet = Snippet(**item)
                self.snippets[snippet.name] = snippet

            print(f"[Snippets] Loaded {len(self.snippets)} snippets from {self.snippets_path}")
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Snippets] Warning: could not load snippets ({exc})")
            self._create_default_snippets()

    def _create_default_snippets(self):
        """Create default example snippets."""
        defaults = [
            Snippet(
                name="email_signature",
                trigger="email signature",
                content="Best regards,\n{name}\n{title}\n{company}\n{phone}",
                description="Professional email signature with placeholders",
                category="email",
                variables={"name": "Your Name", "title": "Your Title", "company": "Company", "phone": "Phone"},
            ),
            Snippet(
                name="meeting_link",
                trigger="meeting link",
                content="Join our meeting: {meeting_url}",
                description="Quick meeting link insertion",
                category="meeting",
                variables={"meeting_url": "https://meet.example.com/..."},
            ),
            Snippet(
                name="todo_template",
                trigger="todo template",
                content="## {date} - Tasks\n\n- [ ] {task1}\n- [ ] {task2}\n- [ ] {task3}\n",
                description="Daily todo list template",
                category="productivity",
                variables={"date": "Today", "task1": "Task 1", "task2": "Task 2", "task3": "Task 3"},
            ),
            Snippet(
                name="code_block",
                trigger="code block",
                content="```{language}\n{code}\n```",
                description="Markdown code block with language",
                category="developer",
                variables={"language": "python", "code": "# Your code here"},
            ),
        ]

        for snippet in defaults:
            self.snippets[snippet.name] = snippet
        self.save()

    def save(self):
        """Save snippets to JSON file."""
        try:
            data = {
                "version": 1,
                "snippets": [asdict(s) for s in self.snippets.values()],
            }
            with open(self.snippets_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            print(f"[Snippets] Warning: could not save snippets ({exc})")

    def add_snippet(self, snippet: Snippet):
        """Add or update a snippet."""
        self.snippets[snippet.name] = snippet
        self.save()

    def remove_snippet(self, name: str) -> bool:
        """Remove a snippet by name."""
        if name in self.snippets:
            del self.snippets[name]
            self.save()
            return True
        return False

    def get_snippet(self, name: str) -> Optional[Snippet]:
        """Get a snippet by name."""
        return self.snippets.get(name)

    def list_snippets(self, category: Optional[str] = None) -> List[Snippet]:
        """List all snippets, optionally filtered by category."""
        result = list(self.snippets.values())
        if category:
            result = [s for s in result if s.category == category]
        return result

    def get_categories(self) -> List[str]:
        """Get all unique categories."""
        return sorted(set(s.category for s in self.snippets.values()))

    def find_matching_snippet(self, transcript: str) -> Optional[Snippet]:
        """
        Find a snippet whose trigger phrase matches the transcript.
        Matches if trigger is contained in transcript (case-insensitive).
        """
        transcript_lower = transcript.lower().strip()
        for snippet in self.snippets.values():
            if not snippet.enabled:
                continue
            trigger_lower = snippet.trigger.lower()
            # Exact match or trigger as a complete phrase in transcript
            if trigger_lower == transcript_lower or f" {trigger_lower} " in f" {transcript_lower} ":
                return snippet
        return None

    def expand_snippet(self, snippet: Snippet, variables: Optional[Dict[str, str]] = None) -> str:
        """
        Expand a snippet with variable substitution.
        Uses snippet defaults, then overrides with provided variables.
        """
        content = snippet.content
        merged_vars = dict(snippet.variables)
        if variables:
            merged_vars.update(variables)

        # Replace {variable} placeholders
        for key, value in merged_vars.items():
            content = content.replace(f"{{{key}}}", value)

        return content


# Default path for snippets file
def get_snippets_path(base_dir: str) -> str:
    return os.path.join(base_dir, "snippets.json")


# Voice command mappings for snippet actions
SNIPPET_COMMANDS = {
    "snippet": "insert_snippet",       # "snippet email signature"
    "insert snippet": "insert_snippet",
    "add snippet": "add_snippet",
    "remove snippet": "remove_snippet",
    "list snippets": "list_snippets",
    "snippets": "list_snippets",
}