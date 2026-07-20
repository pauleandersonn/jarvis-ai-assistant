"""Integrations layer — wrappers para serviços externos (WhatsApp Meta, etc).

Padrão:
  - Cada integração expõe uma classe cliente + funções de alto nível
  - Credenciais vêm de env vars (nunca commitadas)
  - Toda chamada retorna dict `{"ok": bool, ...}` pra ser JSON-safe

Pastas:
  - whatsapp.py  -> Meta Cloud API (WhatsApp Business Platform)
"""
