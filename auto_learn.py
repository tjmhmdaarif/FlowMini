"""
auto_learn.py — Auto-Learning Dictionary for FlowMini.

Learns from user corrections: tracks word/phrase mappings that the user
frequently fixes, and can apply high-frequency learned corrections to new
text automatically. Keeps a suggestion list for entries that should be
promoted to the main custom_dictionary.json.

Pure stdlib, offline, deterministic. No network or GUI dependencies.
"""

import json
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


class AutoLearner:
    """Track and apply learned corrections from user editing behaviour."""

    def __init__(self, corrections_path: str, min_suggest_count: int = 2):
        self.corrections_path = corrections_path
        self.min_suggest_count = min_suggest_count
        # raw_word -> {corrected_word: count}
        self._corrections: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._load()

    # -- persistence -----------------------------------------------------------

    def _load(self):
        if os.path.exists(self.corrections_path):
            try:
                with open(self.corrections_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for raw, entries in data.get("corrections", {}).items():
                    for corrected, count in entries.items():
                        self._corrections[raw][corrected] = int(count)
            except Exception as exc:
                print(f"[AutoLearn] Could not load corrections: {exc}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.corrections_path) or ".", exist_ok=True)
            data = {
                "corrections": {
                    raw: dict(counts) for raw, counts in self._corrections.items()
                }
            }
            with open(self.corrections_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[AutoLearn] Could not save corrections: {exc}")

    # -- core API --------------------------------------------------------------

    def record_correction(self, raw_word: str, corrected_word: str, context: str = ""):
        """Record that the user corrected raw_word -> corrected_word."""
        raw_word = raw_word.strip().lower()
        corrected_word = corrected_word.strip()
        if not raw_word or not corrected_word or raw_word == corrected_word.lower():
            return
        self._corrections[raw_word][corrected_word] += 1
        self._save()

    def get_suggestions(self, min_count: Optional[int] = None) -> List[Tuple[str, str, int]]:
        """Return (raw_word, corrected_word, count) for frequent corrections.

        Only corrections seen >= min_count times are returned, sorted by
        frequency (most common first).
        """
        threshold = min_count or self.min_suggest_count
        results = []
        for raw, counts in self._corrections.items():
            for corrected, count in counts.items():
                if count >= threshold:
                    results.append((raw, corrected, count))
        results.sort(key=lambda x: x[2], reverse=True)
        return results

    def apply_learned(self, text: str, min_count: Optional[int] = None) -> str:
        """Apply high-frequency learned corrections to text.

        Only corrections seen >= min_count times are applied. Longer phrases
        are applied first to avoid partial overlaps.
        """
        threshold = min_count or self.min_suggest_count
        # Collect applicable corrections sorted by phrase length (longest first)
        applicable = []
        for raw, counts in self._corrections.items():
            for corrected, count in counts.items():
                if count >= threshold:
                    applicable.append((raw, corrected))
        applicable.sort(key=lambda x: len(x[0]), reverse=True)

        result = text
        for raw, corrected in applicable:
            # Case-insensitive whole-word/phrase replacement
            pattern = re.compile(re.escape(raw), re.IGNORECASE)
            result = pattern.sub(corrected, result)
        return result

    def promote_suggestions(self, dictionary: Dict) -> int:
        """Promote high-frequency corrections into the custom dictionary.

        Returns the number of entries added/updated. The dictionary is modified
        in place (it is the same object loaded by load_dictionary()).
        """
        suggestions = self.get_suggestions()
        added = 0
        mappings = dictionary.get("mappings", {})
        for raw, corrected, _count in suggestions:
            if raw not in mappings:
                mappings[raw] = corrected
                added += 1
        if added:
            dictionary["mappings"] = mappings
        return added

    def get_stats(self) -> Dict:
        """Return a summary of what has been learned."""
        total_raws = len(self._corrections)
        total_corrections = sum(
            sum(counts.values()) for counts in self._corrections.values()
        )
        suggestions = len(self.get_suggestions())
        return {
            "unique_corrections": total_raws,
            "total_corrections": total_corrections,
            "suggestions_ready": suggestions,
        }
