"""
translit.py — offline Latin-script pronunciation (romanization) of spoken
transcripts, for display in the "heard" line.

Whisper transcribes non-Latin languages in their native script (Devanagari,
Kannada, Tamil, ...). This module converts that text into an English-friendly
"pronunciation" form:  नमस्ते दोस्तों -> "namaste doston"
                        ನಮಸ್ತೆ ಸ್ನೇಹಿತರೇ  -> "namaste sneehitare"

Approach
--------
* Indic scripts (Devanagari, Kannada, Telugu, Tamil, Malayalam, Bengali,
  Gujarati, Gurmukhi) share the same syllable structure, so one parser works
  for all of them: consonant [+ vowel sign / virama] / independent vowel /
  anusvara / visarga. Long vowels are doubled (aa/ii/uu/o/oo) for readability.
* Arabic-script Urdu/Arabic/Persian get a letter-level map with a light
  implicit-vowel heuristic (diphthong letters و/ی behave as vowels after a
  consonant, as glides elsewhere).
* Everything else falls back to `unidecode` (excellent for Cyrillic/Greek, and
  harmless elsewhere).

This is display-only — it never affects the text that is pasted.
"""

from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Indic script tables: (vowels, matras, consonants) aligned to Latin values.
# Each entry is a tuple of (characters, values) or None when the script lacks
# that element. Same structural order for every script:
#   consonants:  k kh g gh ng | ch chh j jh ny | t th d dh n | t th d dh n
#                p ph b bh m  | y r l l v sh sh s h
# ---------------------------------------------------------------------------

#: Devanagari (Hindi, Marathi, Nepali + Sanskrit)
_DEVA = dict(
    vowels=("अआइईउऊऋएऐओऔ", "a aa i ii u uu ri e ai o au"),
    matras=("ािीुूृेैोौ", "aa i ii u uu ri e ai o au"),
    cons=("कखगघङचछजझञटठडढणतथदधनपफबभमयरलळवशषसह",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r l l v sh sh s h"),
    halant="्", anusvara="ं", visarga="ः", chandra="ँ", final_nasal="n",
    extra={"ऑ": "o", "ऽ": "a", "ॐ": "om",
           # nukta forms (Perso-Arabic loanwords, retroflex flaps)
           "ज़": "z", "फ़": "f", "क़": "q", "ग़": "gh", "ख़": "kh",
           "ड़": "r", "ढ़": "rh", "ऩ": "n", "ऱ": "r", "य़": "y"},
)

#: Kannada (same consonant layout; codepoints differ).
_KNDA = dict(
    vowels=("ಅಆಇಈಉಊಋಎಏಐಒಓಔ", "a aa i ii u uu ri e e ai o o au"),
    matras=("ಾಿೀುೂೃೆೇೈೊೋೌ", "aa i ii u uu ri e e ai o o au"),
    cons=("ಕಖಗಘಙಚಛಜಝಞಟಠಡಢಣತಥದಧನಪಫಬಭಮಯರಲಳವಶಷಸಹ",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r l l v sh sh s h"),
    halant="್", anusvara="ಂ", visarga="ಃ", chandra="", final_nasal="m",
    extra={"ೞ": "l"},
)

#: Telugu (consonant codepoints share Kannada's block).
_TELU = dict(
    vowels=("అఆఇఈఉఊఋఎఏఐఒఓఔ", "a aa i ii u uu ri e e ai o o au"),
    matras=("ాిీుూృెేైొోౌ".replace("ః", ""), "aa i ii u uu ri e e ai o o au"),
    cons=("కఖగఘఙచఛజఝఞటఠడఢణతథదధనపఫబభమయరలళవశషసహ",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r l l v sh sh s h"),
    halant="్", anusvara="ం", visarga="ః", chandra="", final_nasal="m",
    extra={"ఱ": "r"},
)

#: Tamil.
_TAML = dict(
    vowels=("அஆஇஈஉஊஎஏஐஒஓஔ", "a aa i ii u uu e e ai o o au"),
    matras=("ாிீுூெேைொோௌ", "aa i ii u uu e e ai o o au"),
    cons=("கஙசஜஞடணதநபமயரலளழவஶஷஸஹ",
          "k ng ch j ny t n th n p m y r l l l v sh sh s h"),
    # Tamil has no halant inside words; ் (pulli) used word-finally mostly.
    halant="்", anusvara="ஂ", visarga="ஃ", chandra="", final_nasal="m",
    extra={"ற": "r", "ன": "n", "ஐ": "ai"},
)

#: Malayalam.
_MLYM = dict(
    vowels=("അആഇഈഉഊഋഎഏഐഒഓഔ", "a aa i ii u uu ri e e ai o o au"),
    matras=("ാിീുൂൃെേൈൊോൌ", "aa i ii u uu ri e e ai o o au"),
    cons=("കഖഗഘങചഛജഝഞടഠഡഢണതഥദധനപഫബഭമയരറലളഴവശഷസഹ",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r r l l l v sh sh s h"),
    halant="്", anusvara="ം", visarga="ഃ", chandra="", final_nasal="m",
    extra={"ൻ": "n", "ർ": "r", "ൽ": "l", "ൾ": "l", "ൺ": "n"},
)

#: Bengali / Assamese.
_BENG = dict(
    vowels=("অআইঈউঊঋএঐওঔ", "a aa i ii u uu ri e ai o ou"),
    matras=("ািীুূৃেৈোৌ", "aa i ii u uu ri e ai o ou"),
    cons=("কখগঘঙচছজঝঞটঠডঢণতথদধনপফবভমযরলশষসহ",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r l sh sh s h"),
    halant="্", anusvara="ং", visarga="ঃ", chandra="ঁ", final_nasal="ng",
    extra={"ড়": "r", "ঢ়": "r", "য়": "y", "ৎ": "t"},
)

#: Gujarati.
_GUJR = dict(
    vowels=("અઆઇઈઉઊઋએઐઓઔ", "a aa i ii u uu ri e ai o au"),
    matras=("ાિીુૂૃેૈોૌ", "aa i ii u uu ri e ai o au"),
    cons=("કખગઘઙચછજઝઞટઠડઢણતથદધનપફબભમયરલળવશષસહ",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r l l v sh sh s h"),
    halant="્", anusvara="ં", visarga="ઃ", chandra="ઁ", final_nasal="n",
    extra={"ઑ": "o"},
)

#: Gurmukhi (Punjabi).
_GURU = dict(
    vowels=("ਅਆਇਈਉਊਏਐਓਔ", "a aa i ii u uu e ai o au"),
    matras=("ਾਿੀੁੂੇੈੋੌ", "aa i ii u uu e ai o au"),
    cons=("ਕਖਗਘਙਚਛਜਝਞਟਠਡਢਣਤਥਦਧਨਪਫਬਭਮਯਰਲਲ਼ਵਸਹ",
          "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n "
          "p ph b bh m y r l l v s h"),
    halant="੍", anusvara="ਂ", visarga="", chandra="ਂ", final_nasal="n",
    extra={"ੳ": "u", "ੲ": "i", "ੴ": "ik oankar", "ੱ": "", "ਸ਼": "sh"},
)

#: language base code -> (table, drop word-final schwa)
_LANG_TABLE: Dict[str, dict] = {
    "hi": (_DEVA, True), "mr": (_DEVA, True), "ne": (_DEVA, True),
    "kn": (_KNDA, False), "te": (_TELU, False), "ta": (_TAML, False),
    "ml": (_MLYM, False), "bn": (_BENG, False),
    "gu": (_GUJR, True), "pa": (_GURU, True),
}


#: combining nukta codepoints across the Indic scripts
_NUKTA_CODEPOINTS = {0x093C, 0x09BC, 0x0A3C, 0x0ABC, 0x0B3C, 0x0C3C}


def _build(table: dict) -> dict:
    """Turn character/value strings into ord-keyed lookup dicts."""
    def z(a, b):
        return {ord(c): v for c, v in zip(a, b.split())}
    cons = z(table["cons"][0], table["cons"][1])
    matras = z(table["matras"][0], table["matras"][1])
    vowels = z(table["vowels"][0], table["vowels"][1])
    extra, nukta_mod = {}, {}
    for c, v in table.get("extra", {}).items():
        if len(c) == 1:
            extra[ord(c)] = v
        else:
            # base letter + combining nukta -> nukta-modified value
            nukta_mod[ord(c[0])] = v
    return {
        "VOW": vowels, "MAT": matras, "CON": cons,
        "HAL": ord(table["halant"]) if table["halant"] else None,
        "ANU": ord(table["anusvara"]) if table["anusvara"] else None,
        "VIS": ord(table["visarga"]) if table["visarga"] else None,
        "CHA": ord(table["chandra"]) if table["chandra"] else None,
        "EXTRA": extra, "NUKTAMOD": nukta_mod,
        "NUKTA": _NUKTA_CODEPOINTS,
        "FINAL": table.get("final_nasal", "n"),
    }


_TABLES: Dict[str, dict] = {code: _build(t) for code, (t, _) in _LANG_TABLE.items()}
_DROP_FINAL: Dict[str, bool] = {code: drop for code, (_, drop) in _LANG_TABLE.items()}

_WORD_END = set(" .,;:!?)]}'\u201d\u2019\u0964\u0965")


def _transliterate_indic(text: str, code: str) -> str:
    T = _TABLES[code]
    drop_final = _DROP_FINAL.get(code, True)
    out: list = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        cp = ord(ch)
        if ch.isspace() or cp < 128 or ch in ",.;:!?()[]'\"":
            out.append(ch)
            i += 1
            continue
        if cp in T["EXTRA"]:
            out.append(T["EXTRA"][cp]); i += 1; continue
        if cp in T["NUKTA"]:
            i += 1; continue
        if cp == T["HAL"]:
            i += 1; continue
        if cp == T["ANU"] or cp == T["CHA"]:
            # anusvara -> FINAL when word-final; "m" before a following labial
            # (p ph b bh m) otherwise "n". Look only within the word.
            j = i + 1
            nxt = ord(text[j]) if j < n else None
            char_next = text[j] if j < n else ""
            word_final = (nxt is None) or char_next.isspace() or (char_next in _WORD_END)
            if word_final:
                out.append(T["FINAL"])
            else:
                labial = any(c == nxt and v[0] in "pbm" for c, v in T["CON"].items())
                out.append("m" if labial else "n")
            i += 1; continue
        if cp == T["VIS"]:
            out.append("h"); i += 1; continue
        if cp in T["VOW"]:
            out.append(T["VOW"][cp]); i += 1; continue
        if cp in T["MAT"]:
            # stray vowel sign (rare) — map it anyway
            out.append(T["MAT"][cp]); i += 1; continue
        if cp in T["CON"] or cp in T["NUKTAMOD"]:
            val = T["CON"].get(cp, "")
            # a following combining nukta selects the modified letter
            k = i + 1
            if k < n and ord(text[k]) in T["NUKTA"]:
                val = T["NUKTAMOD"].get(cp, val)
                k += 1
            nxt = text[k] if k < n else None
            # special conjunct: ज्ञ -> "gy"
            if nxt and ord(nxt) == T["HAL"] and k + 1 < n and \
               T["CON"].get(ord(text[k + 1])) == "ny" and val == "j":
                out.append("gy"); i = k + 2; continue
            if nxt and ord(nxt) == T["HAL"]:
                out.append(val); i = k + 1; continue
            if nxt and ord(nxt) in T["MAT"]:
                out.append(val + T["MAT"][ord(nxt)]); i = k + 1; continue
            # inherent vowel: 'a', dropped word-finally when the language does
            at_end = (k >= n) or (text[k] in _WORD_END)
            out.append(val if (at_end and drop_final) else val + "a")
            i = k; continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Urdu / Arabic / Persian (Arabic script) — letter-level romanization
# ---------------------------------------------------------------------------

#: consonant letters -> latin value (ع handled separately, Urdu extras included)
_ARABIC_CON_MAP = {
    "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s",
    "ج": "j", "چ": "ch", "ح": "h", "خ": "kh",
    "د": "d", "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh",
    "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z",
    "غ": "gh", "ف": "f", "ق": "q", "ک": "k", "گ": "g", "ل": "l", "م": "m",
    "ن": "n", "ہ": "h", "ھ": "h", "ه": "h", "ة": "t",
}
_CON_LETTERS = set(_ARABIC_CON_MAP)

#: alif-family — plain vowel carriers (آ carries a long aa)
_ALIF_LETTERS = set("اآأإ")

#: glide letters: value after a consonant (vowel), value elsewhere (glide)
_GLIDE_LETTERS = {"و": ("v", "o"), "ی": ("y", "i"), "ي": ("y", "i"), "ے": ("e", "e")}

_DIACRITICS = set(map(chr, range(0x064B, 0x0653))) | {"\u0670", "\u0654", "\u0655"}

#: punctuation / hamza carriers / tatweel seen in Arabic-script text
_ARABIC_EXTRA = {
    "ئ": "y", "ؤ": "v", "ء": "", "\u0640": "",
    "\u060C": ",", "\u061B": ";", "\u061F": "?", "\u06D4": ".",
    "\u066A": "%", "\u066B": "", "\u066C": "", "\u064B": "",
}


def _transliterate_arabic(text: str) -> str:
    out: list = []
    prev_cons = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        cp = ord(ch)
        if ch.isspace() or cp < 128 or ch in ",.;:!?()[]'\"":
            out.append(ch); prev_cons = False; i += 1; continue
        if ch in _ALIF_LETTERS:
            out.append("aa" if ch == "آ" else "a")
            prev_cons = False; i += 1; continue
        if ch in _GLIDE_LETTERS:
            glide, vowel = _GLIDE_LETTERS[ch]
            out.append(vowel if prev_cons else glide)
            prev_cons = False; i += 1; continue
        if ch == "ع":
            # soft glottal — often a silent carrier; a faint schwa keeps flow
            out.append("")
            prev_cons = True; i += 1; continue
        if ch in _ARABIC_EXTRA:
            out.append(_ARABIC_EXTRA[ch])
            prev_cons = False; i += 1; continue
        if ch in _CON_LETTERS:
            out.append(_ARABIC_CON_MAP[ch])
            # light implicit short vowel before another consonant within the
            # same word (skip combining marks, but never bridge a space, and
            # never break an aspirated digraph ending in ھ)
            j = i + 1
            while j < n and text[j] in _DIACRITICS:
                j += 1
            if j < n and text[j] in _CON_LETTERS and text[j] != "ھ":
                out.append("a")
            prev_cons = True; i += 1; continue
        if ch in _DIACRITICS:
            i += 1; continue
        # unknown Arabic-script glyph: drop rather than leak it into the heard line
        if cp >= 0x0600:
            i += 1
            continue
        out.append(ch)
        prev_cons = False
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

try:
    from unidecode import unidecode as _unidecode
except Exception:  # pragma: no cover
    _unidecode = None


_SCRIPT_PLAN = {
    "hi": "indic", "mr": "indic", "ne": "indic", "kn": "indic", "te": "indic",
    "ta": "indic", "ml": "indic", "bn": "indic", "gu": "indic", "pa": "indic",
    "ur": "arab", "ar": "arab", "fa": "arab",
}

#: (unicode range, script, language base code used for the table)
_SCRIPT_RANGES = (
    (0x0900, 0x097F, "indic", "hi"),   # Devanagari
    (0x0980, 0x09FF, "indic", "bn"),   # Bengali
    (0x0A00, 0x0A7F, "indic", "pa"),   # Gurmukhi
    (0x0A80, 0x0AFF, "indic", "gu"),   # Gujarati
    (0x0B80, 0x0BFF, "indic", "ta"),   # Tamil
    (0x0C00, 0x0C7F, "indic", "te"),   # Telugu
    (0x0C80, 0x0CFF, "indic", "kn"),   # Kannada
    (0x0D00, 0x0D7F, "indic", "ml"),   # Malayalam
    (0x0600, 0x06FF, "arab", "ar"),    # Arabic / Urdu
    (0x0750, 0x077F, "arab", "ar"),    # Arabic supplement
)


def _detect_script(text: str):
    """Return (plan, table_lang) for the first non-Latin script found."""
    for ch in text:
        cp = ord(ch)
        if cp < 0x0600:
            continue
        for lo, hi, plan, lang in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                return plan, lang
    return None, None


def romanize(text: str, lang: Optional[str] = None) -> str:
    """Return the Latin-script pronunciation of `text` for display.

    The original transcript is never mutated; English/Latin input is returned
    unchanged. The script is detected from the text itself (so a wrong language
    hint cannot break it); unsupported scripts fall back to unidecode.
    """
    if not text:
        return text
    plan, table_lang = _detect_script(text)
    if plan == "indic":
        return _transliterate_indic(text, table_lang)
    if plan == "arab":
        return _transliterate_arabic(text)
    # No Indic/Arabic script: try unidecode for other scripts (Cyrillic,
    # Greek, CJK, ...). Only when there are non-Latin *letters* so that
    # emoji/symbols are left untouched.
    if _unidecode is not None and any(c.isalpha() and ord(c) > 0x00FF for c in text):
        try:
            return _unidecode(text)
        except Exception:
            return text
    return text