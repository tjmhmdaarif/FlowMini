"""Acceptance tests for the Speech Transform Engine (spec §10).

Runnable with plain python (stdlib only):  python tests_speech_transform.py
"""
import sys
import os

sys.path.insert(0, r"C:\Users\muham\OneDrive\Documents\openrouter_projects")
from speech_transform import transform_transcript, TransformResult  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, expected):
    global PASS, FAIL
    ok = got == expected
    if ok:
        PASS += 1
        print(f"  ok    {name}: {got!r}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}:\n        expected {expected!r}\n        got      {got!r}")


def light(t, **kw):
    kw.setdefault("asr_language", "en")
    kw.setdefault("asr_confidence", 0.99)
    return transform_transcript(t, cleanup_mode="light", **kw).finalText


print("== §10 Acceptance: successful transformations ==")
check("commands bracket", light("open square bracket x close square bracket"), "[x]")
check("ordinary word kept", light("I need a bracket"), "I need a bracket.")
check("literal protection", light("type the words open square bracket"),
      "type the words open square bracket.")
check("filler um", light("um, send it today"), "Send it today.")
check("filler uh", light("I, uh, agree"), "I agree.")
check("ambiguous like", light("I like this"), "I like this.")
check("correction actually", light("meet Tuesday, actually Wednesday"), "Meet Wednesday.")
check("no false correction", light("I actually like this"), "I actually like this.")

print("== §10 Acceptance: off mode ==")
r = transform_transcript("um, send it today", cleanup_mode="off")
check("off returns raw", r.finalText, "um, send it today")
check("off no edits", len(r.edits), 0)

print("== §2/§3 example ==")
r = transform_transcript(
    "type open square bracket x close square bracket",
    asr_language="en", asr_confidence=0.96, cleanup_mode="light")
check("example final", r.finalText, "type [x]")
check("example edits", [e.replacement for e in r.edits], ["[", "]"])
check("raw preserved", r.rawTranscript, "type open square bracket x close square bracket")
if r.edits:
    e = r.edits[0]
    check("offsets zero-based", r.rawTranscript[e.start:e.end], "open square bracket")

print("== §3 more command examples ==")
check("bracket with words inside", light("put x inside open square bracket x plus one close square bracket"),
      "Put x inside [x plus one]")
check("plus one NOT converted", "x plus one" in
      light("put x inside open square bracket x plus one close square bracket"), True)
check("new line", light("line one new line line two"), "Line one\nline two.")
check("new paragraph", light("part one new paragraph part two"), "Part one\n\npart two.")
check("question mark", light("where are you question mark"), "Where are you?")
check("comma", light("apples comma oranges and bananas"), "Apples, oranges and bananas.")

print("== §4 filler behavior ==")
check("it looks like a bracket", light("it looks like a bracket"), "It looks like a bracket.")
check("bare like kept", light("I like this"), "I like this.")
check("filler mid-sentence", light("we um need this"), "We need this.")

print("== §5 self-corrections ==")
check("no, replacement", light("use the blue one, no, the red one"), "Use the red one.")
check("scratch that", light("let us meet at five, scratch that, let us meet at six"),
      "Let us meet at six.")
check("I mean", light("call john, I mean, call jane"), "Call jane.")
check("make that", light("buy the black one, make that, the blue one"), "Buy the blue one.")
check("no replacement -> preserved", light("meet Tuesday, no,"),
      "Meet Tuesday, no.")
check("marker without comma -> preserved", light("a b no c"), "A b no c.")

print("== §10 language cases ==")
r = transform_transcript("hola como estas", asr_language="es", asr_confidence=0.94,
                         enabled_languages=["en", "es"], cleanup_mode="light")
check("non-English uses its own rules (transcript preserved)", r.finalText, "hola como estas")
check("es decision", r.languageDecision, "automatic")
check("es detected", r.detectedLanguage, "es")
check("es no-rule warning", any("rules" in w for w in r.warnings), True)

r = transform_transcript("um, send it today", asr_language="xx", asr_confidence=0.1,
                         enabled_languages=["en"], cleanup_mode="light")
check("low confidence + no hint -> ambiguous, preserved", r.finalText, "um, send it today")
check("ambiguous flagged", r.languageDecision, "ambiguous")
check("ambiguous warning present", any("determine" in w for w in r.warnings), True)

r = transform_transcript("open square bracket x close square bracket",
                         asr_language="en", asr_confidence=0.99,
                         enabled_languages=["en"], cleanup_mode="light")
check("automatic decision", r.languageDecision, "automatic")
check("confidence carried", r.languageConfidence, 0.99)

r = transform_transcript("open square bracket x close square bracket",
                         language_hint="en-US", asr_language="en",
                         asr_confidence=0.99, cleanup_mode="light")
check("confident auto with matching hint", r.languageDecision, "automatic")

print("== §9 failure handling ==")
r = transform_transcript("i actually like this", asr_language="fr", asr_confidence=0.99,
                         enabled_languages=["en"], cleanup_mode="light")
check("unsupported language preserved", r.finalText, "i actually like this")
check("unsupported warned", any("rules" in w for w in r.warnings), True)

print("== medium mode ==")
r = transform_transcript("um, send it today", asr_language="en", asr_confidence=0.99,
                         cleanup_mode="medium",
                         medium_rewriter=lambda s: s.replace("Send", "Email"))
check("medium rewrites", r.finalText, "Email it today.")
check("medium edit logged", any(e.type == "formatting" for e in r.edits), True)
r = transform_transcript("um, send it today", asr_language="en", asr_confidence=0.99,
                         cleanup_mode="medium",
                         medium_rewriter=lambda s: None)
check("medium rewriter failure -> light result", r.finalText, "Send it today.")

print("== user command aliases ==")
r = transform_transcript("open curly brace", asr_language="en", asr_confidence=0.99,
                         cleanup_mode="light",
                         user_dictionary={"commandAliases": {"open curly brace": "{"}})
check("alias converts", r.finalText, "{")
r = transform_transcript("open curly brace", asr_language="en", asr_confidence=0.99,
                         cleanup_mode="light")
check("without alias stays words", r.finalText, "Open curly brace.")

print("== undo / raw preservation ==")
r = transform_transcript("open square bracket x close square bracket",
                         asr_language="en", asr_confidence=0.99, cleanup_mode="light")
check("rawTranscript always kept", r.rawTranscript, "open square bracket x close square bracket")

print(f"\n==== RESULT: {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)