"""Quick smoke test for the researcher module."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from Brain.researcher import research, needs_web_search

print("=== needs_web_search tests ===")
for q in [
    "quem ganhou o jogo do palmeiras ontem",
    "como você está?",
    "python 3.14 latest version",
    "me conta uma piada",
    "cotação do dólar hoje",
]:
    print(f"  needs_web_search({q!r}) = {needs_web_search(q)}")

print()
print("=== real research test ===")
r = research("latest python 3.14 release news")
print(f"  context_used: {r['context_used']} pages")
print(f"  sources: {len(r['sources'])}")
for s in r["sources"][:3]:
    title = s["title"][:60] if s["title"] else "(no title)"
    url = s["url"][:80] if s["url"] else ""
    print(f"    - {title}")
    print(f"      {url}")

print()
print("  ANSWER:")
print(" ", r["answer"][:600])