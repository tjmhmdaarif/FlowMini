"""Acceptance tests for translit.py — the offline pronunciation romanizer.

Run:  .venv\\Scripts\\python.exe tests_translit.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translit import romanize

PASS = FAIL = 0


def check(name, got, *must_contain):
    global PASS, FAIL
    missing = [m for m in must_contain if m not in got]
    if missing:
        FAIL += 1
        print(f"  FAIL {name}: {got!r}  missing {missing}")
    else:
        PASS += 1
        print(f"  ok   {name}: {got}")


def check_eq(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok   {name}: {got!r}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: got {got!r} want {want!r}")


print("== Indic scripts ==")
check("hindi",      romanize("नमस्ते दोस्तों, आज का मौसम बहुत अच्छा है", "hi"),
      "namaste", "doston", "aaj", "kaa", "mausam", "bahut", "hai")
check("hindi-2",    romanize("मैंने कल रात खाना खाया", "hi"),
      "mai", "kal", "raat", "khaanaa", "khaayaa")
check("hindi-nukta", romanize("ज़रूरी फ़ोन", "hi"), "zaruuri", "fon")
check("kannada",    romanize("ನಮಸ್ತೆ ಸ್ನೇಹಿತರೇ, ಇಂದು ಹವಾಮಾನ ಚೆನ್ನಾಗಿದೆ", "kn"),
      "namaste", "snehitare", "indu", "havaamaana", "chennaagide")
check("telugu",     romanize("నమస్తే స్నేహితులారా, ఈరోజు వాతావరణం బాగుంది", "te"),
      "namaste", "snehitulaaraa", "vaataavaranam", "baagundi")
check("tamil",      romanize("வணக்கம் நண்பர்களே, இன்று வானிலை நன்றாக இருக்கிறது", "ta"),
      "vanakkam", "inru", "vaanilai")
check("malayalam",  romanize("നമസ്കാരം സുഹൃത്തുക്കളേ, ഇന്ന് കാലാവസ്ഥ നല്ലതാണ്", "ml"),
      "namaskaaram", "kaalaavastha")
check("bengali",    romanize("নমস্কার বন্ধুরা, আজকের আবহাওয়া খুব ভালো", "bn"),
      "namaskaara", "bandhuraa", "aajakera", "khuba", "bhaalo")
check("gujarati",   romanize("નમસ્તે મિત્રો, આજનું હવામાન ખૂબ સારું છે", "gu"),
      "namaste", "mitro", "havaamaan", "khuub", "saarun", "chhe")
check("marathi",    romanize("नमस्कार मित्रांनो, आजचे हवामान छान आहे", "mr"),
      "namaskaar", "mitraanno", "havaamaan", "chhaan", "aahe")
check("nepali",     romanize("नमस्ते साथीहरू, आजको मौसम राम्रो छ", "ne"),
      "namaste", "saathiiharuu", "mausam", "raamro")
check("punjabi",    romanize("ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਦੋਸਤੋ, ਅੱਜ ਦਾ ਮੌਸਮ ਬਹੁਤ ਵਧੀਆ ਹੈ", "pa"),
      "sat", "srii", "akaal", "dos", "mausam", "bahut", "hai")

print("== Arabic-script ==")
check("urdu",   romanize("السلام علیکم دوستو، آج موسم بہت اچھا ہے", "ur"),
      "aaj", "mosam", "bahat", "achha", "he")
check("arabic", romanize("مرحبا يا أصدقاء، الطقس جميل اليوم", "ar"),
      "marahaba", "jamil")

print("== other scripts via unidecode ==")
check("russian", romanize("Привет друзья, сегодня хорошая погода", "ru"),
      "Privet", "pogoda")

print("== latin passthrough / robustness ==")
check_eq("english-untouched", romanize("Hello friends, how are you?", "en"),
         "Hello friends, how are you?")
check_eq("spanish-untouched", romanize("hola amigos", "es"), "hola amigos")
check_eq("script-detect-hi-under-en", romanize("नमस्ते", "en"), "namaste")
check_eq("empty", romanize("", "hi"), "")
check_eq("english-under-hi-wrong-hint", romanize("hello world", "hi"), "hello world")

print(f"\n==== RESULT: {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)
