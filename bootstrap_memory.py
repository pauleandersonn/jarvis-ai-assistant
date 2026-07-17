"""Bootstrap script — creates one .md file per project.

Run once. Idempotent (won't overwrite existing files).
"""

import pathlib

PROJECTS = [
    ("indica-ai", "Indica AI"),
    ("we-love-memory", "We Love Memory"),
    ("luap-studio", "Luap Studio"),
    ("pollar", "Pollar Agência"),
    ("jf-alimentacao", "JF Alimentação"),
    ("hubcare", "HubCare"),
    ("ofertas-zero92", "Ofertas Zero92"),
    ("midia-criativa-do-reino", "Mídia Criativa do Reino"),
    ("finance-agent", "Finance Agent"),
]

TEMPLATE = """---
name: {name}
slug: {slug}
type: project
status: active
---

# {name}

## Objetivo
*(definir o propósito principal deste projeto)*

## Tarefas atuais
- [ ] Definir escopo inicial
- [ ] Listar primeiros entregáveis

## Pendências
*(nenhuma registrada)*

## Próximos passos
*(definir após primeira conversa)*

## Decisões tomadas
*(nenhuma registrada)*

## Arquivos relacionados
*(vincular quando o projeto ganhar estrutura)*

---
Última atualização: {date}
"""

base = pathlib.Path(__file__).resolve().parent / "Memory" / "Projects"
base.mkdir(parents=True, exist_ok=True)

for slug, name in PROJECTS:
    target = base / f"{slug}.md"
    if target.exists():
        print(f"  skip  {slug}.md (already exists)")
        continue
    target.write_text(
        TEMPLATE.format(name=name, slug=slug, date=__import__("datetime").date.today()),
        encoding="utf-8",
    )
    print(f"  ok    {slug}.md")

print(f"\nTotal: {len(PROJECTS)} projects registered.")