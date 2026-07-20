"""Speech normalization — cleanup de markdown / pontuacao / simbolos
ANTES de mandar pro TTS.

Problema: o JARVIS copia/cola markdown cru no TTS, e o Edge TTS
fala LITERALMENTE "asterisco asterisco texto asterisco asterisco".
Pra soar natural, a gente normaliza antes:

  **negrito**        -> "negrito"
  *italico*          -> "italico"
  __sublinhado__     -> "sublinhado"
  _enfase_           -> "enfase"
  `codigo`           -> "codigo"
  # titulo           -> "titulo"
  [texto](link)      -> "texto link"
  ---                -> ""
  1. item            -> "item"
  - item             -> "item"
  * item             -> "item"
  :) :( :D ;) <3     -> "" (emojis textuais removidos; emoticons faciais mantidos)

Multi-pontuacao:
  !? !! ?!?!?!       -> um unico sinal natural
  ...                -> virgula (pausa natural)
  --                 -> virgula
  -                  -> espaco (se for hifen solto, nao for parte de palavra)

Esta funcao e o UNICO lugar onde essa logica vive — tanto Edge_TTS
quanto Fast_DF_TTS importam daqui. DRY.
"""

import re

# ── Markdown markers que o Edge TTS fala como "asterisco" ──
_MD_BOLD = re.compile(r"\*+([^*\n]+?)\*+")            # **bold** ou *bold*
_MD_UNDERSCORE = re.compile(r"_+([^_\n]+?)_+")        # __under__ ou _under_
_MD_CODE = re.compile(r"`([^`\n]+?)`")                # `code`
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")       # [text](url)
_MD_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)  # # titulo no inicio da linha
_MD_HEADER_INLINE = re.compile(r"\s#{1,6}\s+")                  # # titulo inline (depois de espaco)
_MD_HRULE = re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE)    # --- ou ___ na linha inteira
# Separador inline cercado por espacos (--- entre palavras, nao hifen solto)
_MD_HRULE_INLINE = re.compile(r"(?<=\s)[-*_]{3,}(?=\s)")        # exige espaco antes e depois
_MD_BULLET_NUM = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)     # 1. item
_MD_BULLET_DASH = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)    # - item

# Emojis textuais comuns (sem valor semantico quando falados)
_TEXT_EMOJI = re.compile(r"[:;][)D(]|:-?[)D(]|<3|</3|>:-\(")

# Multi-pontuacao (Edge TTS fala "exclamacao interrogacao exclamacao").
# Captura uma sequencia MISTA como "?!!?!" e mantem so o ULTIMO sinal.
# Usa lookahead pra manter o caractere final.
_MULTI_PUNCT_LAST = re.compile(r"[!?]+([!?])")
_HR_REPLACEMENT = "\u2026"   # reticencias Unicode (Edge pausa natural)

# Reticencias explicitas -> virgula (pausa curta, natural)
_ELLIPSIS = re.compile(r"\.{3,}")
_DASH_DOUBLE = re.compile(r"(?<!-)-(?!-).*?-(?!-)")  # nao captura ----

# Backtick/aspas tipograficas
_SMART_QUOTES = re.compile(r"[\u201c\u201d\u2018\u2019]")


def normalize_for_speech(text: str) -> str:
    """Limpa markdown/pontuacao pra TTS soar natural.

    Idempotente: rodar 2x nao muda o resultado.
    """
    if not text:
        return ""

    # ── Markdown ──
    text = _MD_BOLD.sub(r"\1", text)         # **negrito** -> negrito
    text = _MD_UNDERSCORE.sub(r"\1", text)    # __sub__ -> sub
    text = _MD_CODE.sub(r"\1", text)          # `code` -> code
    text = _MD_LINK.sub(r"\1 link", text)     # [text](url) -> text link
    text = _MD_HEADER.sub("", text)           # # titulo no inicio -> titulo
    text = _MD_HEADER_INLINE.sub(" ", text)   # # titulo inline -> espaco
    text = _MD_HRULE.sub("", text)            # --- numa linha -> ""
    text = _MD_BULLET_NUM.sub("", text)       # 1. -> ""
    text = _MD_BULLET_DASH.sub("", text)      # - -> ""
    text = _TEXT_EMOJI.sub("", text)          # :) :( etc -> ""

    # Reticencias explicitas -> virgula (pausa curta, natural)
    text = _ELLIPSIS.sub(", ", text)

    # Hifen/underscore/asterisco triplo cercado por espacos -> remove (sem virgula)
    text = _MD_HRULE_INLINE.sub("", text)

    # Multi-pontuacao: mantem so o ULTIMO sinal (Edge TTS nao fala "exclamacao interrogacao").
    # "?!?!" -> "?".  "!!!" -> "!".
    text = _MULTI_PUNCT_LAST.sub(r"\1", text)

    # Aspas tipograficas -> aspas normais
    text = _SMART_QUOTES.sub('"', text)

    # Hifen duplo: vira virgula
    text = re.sub(r"--+", ", ", text)

    # Espacos multiplos
    text = re.sub(r"\s+", " ", text).strip()

    return text


# Self-test (rodar com `python -m TextToSpeech.normalizer`)
if __name__ == "__main__":
    test_cases = [
        ("**negrito** e *italico*", "negrito e italico"),
        ("`código` e # título", "código e título"),
        ("[link](https://x.com) ok", "link link ok"),
        ("Olá!!! Como vai?? Tudo bem?!", "Olá! Como vai? Tudo bem!"),  # mantem ultimo char
        ("Pensando...", "Pensando,"),
        ("- item um\n- item dois", "item um item dois"),
        ("1. primeiro\n2. segundo", "primeiro segundo"),
        ("---", ""),                              # HRULE puro (linha so com ---)
        ("--- separador", ", separador"),        # inicio de linha: virgula + palavra
        ("texto --- separador", "texto separador"),  # --- cercado por espacos: remove
        ("olha :) que legal :D", "olha que legal"),
    ]
    for inp, expected in test_cases:
        out = normalize_for_speech(inp)
        status = "OK" if out == expected else "FAIL"
        print(f"  [{status}] {inp!r:50s} -> {out!r}")
        if status == "FAIL":
            print(f"        expected: {expected!r}")