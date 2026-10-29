"""
speech_transform.py — Speech Transform Engine (deterministic, post-ASR).

Turns a raw speech-recognition transcript into clean, correctly formatted text:
  * spoken symbol commands    ("open square bracket" -> "[")
  * literal-text protection   ("type the words open bracket" stays as words)
  * unambiguous filler removal ("um" / "uh" / "erm")
  * clear self-corrections     ("meet Tuesday, actually Wednesday" -> "Meet Wednesday.")
  * punctuation & capitalization
  * automatic language detection (automatic | hinted | fallback | ambiguous)
  * cleanup modes: off | light | medium
  * an ordered edit log with source spans (zero-based char offsets)
  * one-step undo support (rawTranscript is always preserved)

Proposed design informed by Wispr Flow's public documentation of filler
cleanup, self-corrections and spoken formatting commands. It does NOT describe
Wispr Flow's internal implementation.

Pure stdlib module: no network, mic or GUI — unit-testable with fixtures.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data tables (extensible config objects)
# ---------------------------------------------------------------------------

#: Default English spoken-symbol command vocabulary (phrase -> literal output).
SPOKEN_COMMANDS: Dict[str, str] = {
    "open square bracket": "[",
    "close square bracket": "]",
    "open bracket": "[",
    "close bracket": "]",
    "left square bracket": "[",
    "right square bracket": "]",
    "open parenthesis": "(",
    "close parenthesis": ")",
    "open paren": "(",
    "close paren": ")",
    "comma": ",",
    "period": ".",
    "question mark": "?",
    "exclamation point": "!",
    "new line": "\n",
    "next line": "\n",
    "new paragraph": "\n\n",
}

#: Unambiguous filler words per language (hesitation only, carries no meaning).
FILLERS: Dict[str, set] = {"en": {"um", "uh", "erm"}}

#: Words that MIGHT be fillers; preserved by default (ambiguous).
AMBIGUOUS_FILLERS: Dict[str, set] = {"en": {"like", "so", "you know", "well", "i mean"}}

#: Self-correction markers per language.
CORRECTION_MARKERS: Dict[str, set] = {
    "en": {"actually", "scratch that", "no", "i mean", "make that"},
}

#: Markers that discard the ENTIRE abandoned clause (not just its object).
WHOLE_CLAUSE_MARKERS: set = {"scratch that"}

#: Phrases that make the following span literal text ("write the words, not the symbols").
LITERAL_CUES: Tuple[str, ...] = ("type the words", "write the phrase", "say the words")

#: Words that introduce a sentence object (used to locate the correction frame).
OBJECT_MARKERS: set = {"the", "this", "that", "my", "our", "your", "his", "her", "its", "a", "an"}

#: Final characters after which no extra terminal punctuation is appended.
TERMINALS: set = set(".,;:!?)]}\u201d\u2019")

SUPPORTED_LANGUAGES: set = {"en"}
DEFAULT_CONFIDENCE_THRESHOLD = 0.80
# All TransformEdit offsets are ZERO-BASED char offsets into rawTranscript.

PUNCT_SPLIT = set(',.;:!?()[]"\u201c\u201d')

#: Brackets/parens and comma-like punctuation used by the join rules.
OPEN_SYMBOLS = set("([{")
CLOSE_SYMBOLS = set(")]}")
ATTACH_PREV = set(".,;:!?)]}")


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

@dataclass
class Token:
    text: str
    start: int                 # zero-based char offset in the raw transcript
    end: int                   # exclusive
    kind: str = "word"         # word | punctuation | command | linebreak
    protected: bool = False

    @property
    def normalized(self) -> str:
        return self.text.lower()


@dataclass
class LanguageDecision:
    language: Optional[str] = None
    confidence: float = 0.0
    decision: str = "fallback"     # automatic | hinted | fallback | ambiguous
    warning: Optional[str] = None


@dataclass
class TransformEdit:
    type: str                     # spoken_command | filler_removed | correction | formatting
    sourceText: str
    replacement: str
    start: int                    # zero-based char offset into rawTranscript
    end: int                      # exclusive
    language: Optional[str] = None


@dataclass
class TransformResult:
    rawTranscript: str
    finalText: str
    detectedLanguage: Optional[str] = None
    languageConfidence: Optional[float] = None
    languageDecision: str = "fallback"
    languageWarning: Optional[str] = None
    edits: List[TransformEdit] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def _base(code: str) -> str:
    return (code or "").strip().lower().split("-")[0]


def detect_language(
    transcript: str,
    asr_language: Optional[str] = None,
    asr_confidence: float = 0.0,
    hint: Optional[str] = None,
    enabled_languages: Optional[List[str]] = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> LanguageDecision:
    """Pick the transformation language among enabledLanguages.

    ASR-provided language+confidence is the primary signal; languageHint is a
    strong preference; low confidence falls back or becomes ambiguous. Never
    translates anything.
    """
    enabled = [_base(x) for x in enabled_languages] if enabled_languages else ["en"]
    if not enabled:
        enabled = ["en"]

    hint_base = _base(hint) if hint else None
    asr_base = _base(asr_language) if asr_language else None

    # 1. Confident, supported ASR detection -> automatic.
    if asr_base and asr_base in enabled and asr_confidence >= threshold:
        if hint_base and hint_base != asr_base:
            return LanguageDecision(
                asr_base, asr_confidence, "automatic",
                warning=f"ASR detected '{asr_base}' but you chose '{hint_base}' — using '{asr_base}'.")
        return LanguageDecision(asr_base, asr_confidence, "automatic")

    # 2. Explicit hint wins when ASR is absent or weak.
    if hint_base:
        if asr_base and asr_base != hint_base and asr_confidence >= threshold:
            return LanguageDecision(
                hint_base, asr_confidence, "hinted",
                warning=f"ASR detected '{asr_base}' ({asr_confidence:.0%}) but '{hint_base}' is selected — using '{hint_base}'.")
        if hint_base not in enabled:
            return LanguageDecision(
                hint_base, max(asr_confidence, 0.5), "fallback",
                warning=f"Selected language '{hint_base}' is not enabled; using it anyway.")
        return LanguageDecision(hint_base, max(asr_confidence, 0.5), "hinted")

    # 3. ASR detected a disallowed / weak language.
    if asr_base:
        if asr_confidence < threshold:
            return LanguageDecision(
                None, asr_confidence, "ambiguous",
                warning="Could not confidently determine the spoken language — no transformations applied.")
        return LanguageDecision(
            asr_base, asr_confidence, "fallback",
            warning=f"Detected language '{asr_base}' is not enabled — transformation limited to enabled languages.")

    # 4. Nothing usable.
    return LanguageDecision(
        None, 0.0, "ambiguous",
        warning="Could not determine the spoken language — no transformations applied.")


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def tokenize(text: str) -> List[Token]:
    """Split whitespace runs into word/punctuation tokens, preserving offsets.

    Leading/trailing punctuation is split into its own token so a command phrase
    like 'close square bracket,' never drags the comma along with it.
    """
    tokens: List[Token] = []
    for m in re.finditer(r"\S+", text):
        s, e = m.span()
        raw = m.group(0)
        j = 0
        while j < len(raw) and raw[j] in PUNCT_SPLIT:
            j += 1
        k = len(raw)
        while k > j and raw[k - 1] in PUNCT_SPLIT:
            k -= 1
        if j:
            tokens.append(Token(raw[:j], s, s + j, "punctuation"))
        if k > j:
            tokens.append(Token(raw[j:k], s + j, s + k, "word"))
        if k < len(raw):
            tokens.append(Token(raw[k:], s + k, e, "punctuation"))
    return tokens


# ---------------------------------------------------------------------------
# Literal-text protection
# ---------------------------------------------------------------------------

def protect_literal_spans(tokens: List[Token], cues: Tuple[str, ...] = LITERAL_CUES) -> bool:
    """Find a literal-text cue; protect everything after it. Returns True if found."""
    n = len(tokens)
    cue_lists = [c.strip().split() for c in cues]
    for i in range(n):
        for cue in cue_lists:
            if i + len(cue) <= n and all(
                    tokens[i + k].kind == "word" and tokens[i + k].normalized == cue[k]
                    for k in range(len(cue))):
                for t in tokens[i + len(cue):]:
                    t.protected = True
                return True
    return False


# ---------------------------------------------------------------------------
# Spoken commands
# ---------------------------------------------------------------------------

def apply_commands(
    tokens: List[Token],
    command_map: Dict[str, str],
    language: Optional[str],
) -> Tuple[List[Token], List[TransformEdit], bool]:
    """Replace longest matching spoken phrases with literal symbols.

    Matches on complete, token-aligned phrases only (never inside other words).
    Prefers the longest phrase ('open square bracket' before 'open bracket').
    """
    max_len = max((len(p.split()) for p in command_map), default=1)
    out: List[Token] = []
    edits: List[TransformEdit] = []
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        if tok.kind == "word" and not tok.protected:
            matched = None
            length = 0
            for L in range(min(max_len, n - i), 0, -1):
                window = tokens[i:i + L]
                if len(window) < L:
                    continue
                if any(t.kind != "word" or t.protected for t in window):
                    continue
                phrase = " ".join(t.normalized for t in window)
                if phrase in command_map:
                    matched = command_map[phrase]
                    length = L
                    break
            if matched is not None:
                src_start = tokens[i].start
                src_end = tokens[i + length - 1].end
                edits.append(TransformEdit(
                    "spoken_command", "".join(t.text for t in tokens[i:i + length]),
                    matched, src_start, src_end, language))
                out.append(Token(matched, src_start, src_end, "command"))
                i += length
                continue
        out.append(tok)
        i += 1
    return out, edits, any(e.type == "spoken_command" for e in edits)


# ---------------------------------------------------------------------------
# Fillers
# ---------------------------------------------------------------------------

def apply_fillers(
    tokens: List[Token],
    fillers: set,
    language: Optional[str],
) -> Tuple[List[Token], List[TransformEdit]]:
    """Remove unambiguous filler tokens and one adjacent comma each."""
    out: List[Token] = []
    edits: List[TransformEdit] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.kind == "word" and not tok.protected and tok.normalized in fillers:
            removed_start = tok.start
            removed_text = tok.text
            removed_end = tok.end
            consumed = 0
            # drop a comma that FOLLOWS the filler
            if i + 1 < n and tokens[i + 1].text == ",":
                removed_end = tokens[i + 1].end
                removed_text += ","
                consumed = 1
            # drop a comma that PRECEDES the filler
            if out and out[-1].text == ",":
                rmv = out.pop()
                removed_start = rmv.start
                removed_text = rmv.text + removed_text
            edits.append(TransformEdit("filler_removed", removed_text, "",
                                       removed_start, removed_end, language))
            i += 1 + consumed
            continue
        out.append(tok)
        i += 1
    return out, edits


# ---------------------------------------------------------------------------
# Self-corrections
# ---------------------------------------------------------------------------

def apply_corrections(
    tokens: List[Token],
    markers: set,
    whole_clause: set,
    language: Optional[str],
) -> Tuple[List[Token], List[TransformEdit]]:
    """Resolve the MOST RECENT, clear self-correction: 'X <marker> Y'.

    Requires a comma immediately before the marker and a non-empty replacement Y.
    'scratch that' discards the entire abandoned clause; the other markers keep
    the leading sentence frame (e.g. 'meet' in 'meet Tuesday, actually Wednesday').
    Does nothing when the marker is part of protected literal text, or when the
    correction is ambiguous (no comma, no replacement).
    """
    n = len(tokens)
    spans: List[Tuple[int, int, str]] = []
    for i in range(n):
        for marker in sorted(markers, key=lambda m: -len(m.split())):
            words = marker.split()
            if i + len(words) <= n and all(
                    tokens[i + k].kind == "word" and tokens[i + k].normalized == words[k]
                    for k in range(len(words))):
                spans.append((i, i + len(words), marker))
                break
    if not spans:
        return tokens, []

    i, j, marker = spans[-1]
    # marker must be preceded by a comma and not inside protected text
    if i == 0 or tokens[i - 1].text != ",":
        return tokens, []
    if any(t.protected for t in tokens[i - 1:j]):
        return tokens, []

    # replacement Y starts after the marker; drop a separating comma
    k = j
    if k < n and tokens[k].text == ",":
        k += 1
    y = tokens[k:]
    if not any(t.kind == "word" for t in y):
        return tokens, []  # no plausible replacement -> keep the transcript

    x_toks = tokens[:i - 1]                      # everything before the comma
    x_words = [t for t in x_toks if t.kind == "word"]
    if not x_words:
        return tokens, []

    if marker in whole_clause:
        # discard the ENTIRE abandoned clause, keep the replacement
        kept = list(y)
        removed_toks = tokens[:k]
    else:
        y_words = [t for t in y if t.kind == "word"]
        y_first = y_words[0].normalized if y_words else ""
        # Y is a self-sufficient sentence when it is not a bare fragment
        fragment = (len(y_words) == 1 or
                    y_first in OBJECT_MARKERS or
                    y_first in {"to", "at", "on", "for", "with", "from", "in"})
        if not fragment:
            # "call john, I mean, call jane" -> "call jane"
            kept = list(y)
            removed_toks = tokens[:k]
        else:
            # keep the leading sentence frame of X (up to its last object marker)
            frame_count = len(x_words) - 1
            for idx, tok in enumerate(x_words):
                if tok.normalized in OBJECT_MARKERS:
                    frame_count = idx
            frame_toks: List[Token] = []
            for t in x_toks:
                if t.kind == "word":
                    frame_toks.append(t)
                    if len(frame_toks) == frame_count:
                        break
            kept = list(frame_toks) + list(y)
            if frame_toks:
                last_kept = next(idx for idx, t in enumerate(tokens) if t is frame_toks[-1])
                removed_toks = tokens[last_kept + 1:k]
            else:
                removed_toks = tokens[:k]

    removed_start = removed_toks[0].start
    removed_end = removed_toks[-1].end
    removed_text = "".join(t.text for t in removed_toks)
    edits = [TransformEdit("correction", removed_text, "",
                           removed_start, removed_end, language)]
    return kept, edits


# ---------------------------------------------------------------------------
# Join + formatting
# ---------------------------------------------------------------------------

def join_tokens(tokens: List[Token]) -> str:
    """Rebuild the text with clean spacing around symbols and punctuation.

    - comma/period style punctuation attaches to the previous word
    - a space is inserted before an OPENING bracket and after a CLOSING one
    - nothing sticks inside "[]", "()" pairs; line breaks strip stray spaces
    """
    out = ""
    for tok in tokens:
        t = tok.text
        if t.startswith("\n"):
            out = out.rstrip()
            out += t
            continue
        if not out:
            out = t
            continue
        last = out[-1]
        if t in ATTACH_PREV:            # ", . ; : ! ? ) ] }" hug the word before
            out += t
        elif last in OPEN_SYMBOLS:      # inside an opening bracket
            out += t
        elif t in CLOSE_SYMBOLS:        # before a closing bracket
            out = out.rstrip() + t
        elif last == "\n":              # after a line break
            out += t
        else:
            out += " " + t
    return out


#: Utterances that begin with a dictation verb are kept lowercase ("type [x]").
DICTATION_VERBS: set = {"type", "write", "say"}


def finish_light(text: str) -> str:
    """Normalize spacing, capitalize the sentence start, ensure terminal punctuation.

    - A trailing comma becomes a period (dictated sentence shouldn't end on one).
    - Terminal punctuation is only added when the text ends in a letter/digit
      (so "[x]" and "Where are you?" are not double-terminated).
    - Sentences that start with a dictation verb ("type", "write", "say") are
      kept lowercase, matching literal/dictation phrasing like "type [x]".
    """
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return text
    if text.endswith(","):
        text = text[:-1] + "."
    if text[0].isalpha():
        first_word = re.split(r"[^A-Za-z]", text, maxsplit=1)[0].lower()
        if first_word not in DICTATION_VERBS:
            text = text[0].upper() + text[1:]
    if text[-1].isalnum():
        text += "."
    return text


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def transform_transcript(
    transcript: str,
    language_hint: Optional[str] = None,
    enabled_languages: Optional[List[str]] = None,
    asr_language: Optional[str] = None,
    asr_confidence: float = 0.0,
    cleanup_mode: str = "light",                   # off | light | medium
    user_dictionary: Optional[dict] = None,        # {"commandAliases": {...}}
    medium_rewriter: Optional[Callable[[str], str]] = None,
) -> TransformResult:
    """Run the full pipeline. Pure function; never mutates the input."""
    transcript = transcript or ""
    mode = (cleanup_mode or "light").lower()
    result = TransformResult(rawTranscript=transcript, finalText=transcript,
                             languageDecision="fallback")

    if mode == "off":
        result.warnings.append("cleanupMode=off — returned the raw transcript.")
        return result

    # 1. language decision
    decision = detect_language(transcript, asr_language, asr_confidence,
                               language_hint, enabled_languages)
    result.detectedLanguage = decision.language
    result.languageConfidence = decision.confidence
    result.languageDecision = decision.decision
    if decision.warning:
        result.warnings.append(decision.warning)

    lang = _base(decision.language) if decision.language else None

    if decision.decision == "ambiguous" or lang not in SUPPORTED_LANGUAGES:
        if lang and lang not in SUPPORTED_LANGUAGES:
            result.warnings.append(
                f"No transformation rules for '{lang}' — preserved the transcript.")
        return result  # finalText stays == rawTranscript

    # 2. tokenize + protect literal spans
    tokens = tokenize(transcript)
    literal_found = protect_literal_spans(tokens)

    # 3. command vocabulary (defaults + user aliases)
    command_map = dict(SPOKEN_COMMANDS)
    if user_dictionary:
        command_map.update(user_dictionary.get("commandAliases") or {})

    # 4. spoken commands
    tokens, cmd_edits, _ = apply_commands(tokens, command_map, lang)
    result.edits.extend(cmd_edits)

    # 5. self-corrections
    markers = CORRECTION_MARKERS.get(lang, set())
    if markers:
        tokens, corr_edits = apply_corrections(tokens, markers, WHOLE_CLAUSE_MARKERS, lang)
        result.edits.extend(corr_edits)

    # 6. fillers
    fillers = FILLERS.get(lang, set())
    if fillers:
        tokens, fill_edits = apply_fillers(tokens, fillers, lang)
        result.edits.extend(fill_edits)

    # 7. punctuation & capitalization (light)
    final = join_tokens(tokens)
    if final.strip():
        final = finish_light(final)
    result.finalText = final

    # 8. medium: optional rewrite (kept separate & optional; keeps meaning)
    if mode == "medium" and medium_rewriter:
        try:
            rewritten = medium_rewriter(final)
            if rewritten and rewritten.strip() and rewritten.strip() != final:
                result.edits.append(TransformEdit(
                    "formatting", final, rewritten.strip(), 0, len(transcript), lang))
                result.finalText = rewritten.strip()
        except Exception as exc:  # rewriter failure -> light result
            result.warnings.append(f"Medium rewrite skipped ({exc}).")

    return result


def transform_request(request: dict,
                      medium_rewriter: Optional[Callable[[str], str]] = None) -> TransformResult:
    """Accept a dict-shaped request, as a service boundary would."""
    return transform_transcript(
        transcript=request.get("transcript", ""),
        language_hint=request.get("languageHint"),
        enabled_languages=request.get("enabledLanguages"),
        asr_language=request.get("asrLanguage"),
        asr_confidence=request.get("asrConfidence", 0.0),
        cleanup_mode=request.get("cleanupMode", "light"),
        user_dictionary=request.get("userDictionary"),
        medium_rewriter=medium_rewriter,
    )