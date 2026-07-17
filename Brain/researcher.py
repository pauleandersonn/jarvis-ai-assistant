"""Lightweight web researcher.

This is a slimmed-down version of what gpt-researcher does — for our
jarvis use case (1-2 paragraph answers with sources) we don't need the
full langchain/langgraph stack.

Pipeline:
  1. Take a query.
  2. Search DuckDuckGo for it.
  3. Pick the top N URLs.
  4. Fetch each URL, strip HTML, keep first ~3KB of text.
  5. Ask FreeAI to answer the question citing the gathered context.

Returns: (answer, sources_list).
"""

import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

from Brain.brain import Main_Brain  # reuse the FreeAI chat brain
from rich import print as rprint


# Conservative defaults — web research is slow so we keep things tight.
_MAX_SEARCH_RESULTS = 6
_MAX_PAGES_TO_FETCH = 4
_MAX_CHARS_PER_PAGE = 3000
_FETCH_TIMEOUT = 12  # seconds


def _ddg_search(query: str, max_results: int = _MAX_SEARCH_RESULTS):
    """Return a list of (title, url) tuples from DuckDuckGo HTML."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # legacy package name

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, region="wt-wt"):
                url = r.get("href") or r.get("url")
                title = r.get("title") or url
                if url and url.startswith("http"):
                    results.append((title, url))
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red][researcher] DDG search failed: {exc}[/red]")
    return results


def _fetch_page_text(url: str) -> str:
    """Download a URL and return clean visible text (limited chars)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=_FETCH_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"(could not fetch: {exc})"

    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "header",
                         "footer", "nav", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except Exception as exc:  # noqa: BLE001
        return f"(could not parse: {exc})"

    # Collapse multiple newlines.
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text[:_MAX_CHARS_PER_PAGE]


def research(query: str) -> dict:
    """Run web research for `query` and return a dict with answer + sources.

    Returns: {
        "answer": "...",   # the synthesized answer
        "sources": [{"title": ..., "url": ...}, ...],
        "context_used": int  # how many pages contributed
    }
    """
    # 1) Search.
    hits = _ddg_search(query)
    if not hits:
        return {
            "answer": (
                "Não consegui resultados de busca para essa pergunta. "
                "Tente reformular ou verifique sua conexão."
            ),
            "sources": [],
            "context_used": 0,
        }

    # 2) Fetch top pages.
    context_blocks = []
    sources = []
    pages_used = 0
    for title, url in hits[:_MAX_PAGES_TO_FETCH]:
        text = _fetch_page_text(url)
        if not text or text.startswith("("):
            continue
        context_blocks.append(f"[{title}] ({url})\n{text}")
        sources.append({"title": title, "url": url})
        pages_used += 1

    if not context_blocks:
        return {
            "answer": (
                "Encontrei resultados na busca mas não consegui ler nenhuma "
                "das páginas. Tente novamente em alguns instantes."
            ),
            "sources": [{"title": t, "url": u} for t, u in hits[:3]],
            "context_used": 0,
        }

    # 3) Ask FreeAI to synthesize the answer using the gathered context.
    context = "\n\n---\n\n".join(context_blocks)
    prompt = (
        "Você é Jarvis, um assistente de voz em português do Brasil. "
        "Responda a pergunta do usuário usando APENAS as informações "
        "do contexto abaixo. Se o contexto não tiver a resposta, diga "
        "que não encontrou. Seja direto, no máximo 3 frases, e cite "
        "as fontes no final entre colchetes [1], [2] etc.\n\n"
        f"PERGUNTA: {query}\n\n"
        f"CONTEXTO:\n{context}\n\n"
        "RESPOSTA (em português do Brasil):"
    )
    answer = Main_Brain(prompt)

    return {
        "answer": answer,
        "sources": sources,
        "context_used": pages_used,
    }


# Keywords that suggest the user wants fresh / live data from the web.
_WEB_HINTS = (
    "hoje", "agora", "ontem", "última", "último", "últimas", "últimos",
    "atual", "atualmente", "recentemente", "recente",
    "quem ganhou", "quem é o atual", "qual a cotação",
    "notícia", "notícias", "novidades",
    "previsão do tempo", "vai chover", "vai nevar",
    "python 3.", "versão", "release", "lançamento",
    "ganhou", "perdeu", "resultado", "placar",
    "quando", "onde fica", "como chegar",
    "preço do", "valor do", "quanto custa",
    "wikipedia", "wikipédia",
    "score", "jogo", "partida", "campeonato",
    "election", "eleição", "presidente", "prefeito",
    "stock", "bolsa", "dólar", "euro", "bitcoin",
    " temperatura", "clima em",
    "stock price", "weather in", "news", "latest",
)


def needs_web_search(text: str) -> bool:
    """Return True if `text` looks like a query that needs live web data."""
    t = text.lower()
    return any(hint in t for hint in _WEB_HINTS)