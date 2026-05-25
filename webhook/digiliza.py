"""
webhook/digiliza.py
Cliente para a API do Digiliza (baseado em Chatwoot).

Base URL : https://chat.digiliza.com
Auth     : header  api_access_token: <token>  (userApiKey)

Endpoints utilizados:
  POST /api/v1/accounts/{id}/contacts
  GET  /api/v1/accounts/{id}/contacts/search
  POST /api/v1/accounts/{id}/contacts/{id}/contact_inboxes
  POST /api/v1/accounts/{id}/conversations
  POST /api/v1/accounts/{id}/conversations/{id}/messages
  POST /api/v1/accounts/{id}/conversations/{id}/assignments
  POST /api/v1/accounts/{id}/conversations/{id}/labels
  POST /api/v1/accounts/{id}/webhooks          (registro do webhook de reply)
"""

import logging
import os
import uuid
import httpx

logger = logging.getLogger(__name__)

class DigilizaClient:

    def __init__(self):
        # 1. Carrega as variáveis APENAS na hora que a classe é chamada (após o load_dotenv)
        self.api_url = os.getenv("DIGILIZA_API_URL", "https://chat.digiliza.com")
        self.account_id = os.getenv("DIGILIZA_ACCOUNT_ID", "132") # Fallback para 132
        self.api_key = os.getenv("DIGILIZA_API_KEY", "")

        # 2. Constrói a URL base dinâmica
        self.BASE = f"{self.api_url}/api/v1/accounts/{self.account_id}"

        # 3. Prepara os headers com a chave correta
        self.headers = {
            "api_access_token": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Contatos ──────────────────────────────────────────────────────────────

    async def upsert_contact(self, lead: dict) -> dict:
        """
        Busca o contato pelo telefone ou email. Se não existir, cria.
        Retorna o objeto de contato com `id`.
        """
        existing = None
        
        # 1. Tenta buscar pelo telefone primeiro (chave mais forte no WhatsApp)
        if lead.get("phone_number"):
            # A busca do Digiliza às vezes é sensível ao "+", então enviamos limpo ou como veio
            existing = await self._search_contact(lead["phone_number"])
            
        # 2. Se não achou pelo telefone, tenta pelo email
        if not existing and lead.get("email"):
            existing = await self._search_contact(lead["email"])

        if existing:
            logger.info("Contato já existe: id=%s", existing["id"])
            return existing

        # ... (resto do código continua igual, montando o payload e fazendo o POST) ...
        payload = {
            "inbox_id": lead["inbox_id"],          # obrigatório
            "name": lead["name"],
            "email": lead["email"] or None,
            "phone_number": lead["phone_number"] or None,
            "additional_attributes": {
                "campanha":   lead.get("campanha", ""),
                "utm_source": lead.get("utm_source", ""),
                "utm_medium": lead.get("utm_medium", ""),
                "cidade":     lead.get("cidade", ""),
                "empresa":    lead.get("empresa", ""),
            },
        }
        # Remove campos None para evitar erros de validação
        payload = {k: v for k, v in payload.items() if v is not None}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.BASE}/contacts",
                json=payload,
                headers=self.headers,
            )

            # === DEBUG DO ERRO 422 ===
            if resp.status_code == 422:
                logger.error("Erro 422 no payload enviado: %s", payload)
                logger.error("Motivo da recusa pelo Digiliza: %s", resp.text)
            # =========================

            resp.raise_for_status()
            data = resp.json()
            contact = data.get("payload", data)
            if isinstance(contact, list):
                contact = contact[0]
            logger.info("Contato criado: id=%s", contact.get("id"))
            return contact

    async def _search_contact(self, query: str) -> dict | None:
        """
        Busca contato por email, nome, telefone ou identifier.
        Retorna None se não encontrado.
        """
        if not query:
            return None
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE}/contacts/search",
                params={"q": query, "page": 1},
                headers=self.headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get("payload", [])
                if contacts:
                    return contacts[0]
        return None

    # ── Conversas ─────────────────────────────────────────────────────────────

    async def create_conversation(
        self,
        contact_id: int,
        inbox_id: int,
        phone_number: str = "",
        meta: dict | None = None,
        primeira_mensagem: str = "",
    ) -> dict:
        """
        Cria uma nova conversa no Digiliza.
        """
        phone_digits = "".join(c for c in (phone_number or "") if c.isdigit())
        source_id = f"{phone_digits}_{uuid.uuid4().hex[:8]}@c.us" if phone_digits else str(contact_id)
        payload: dict = {
            "source_id": source_id,   # obrigatório
            "inbox_id": inbox_id,      # obrigatório
            "contact_id": contact_id,
            "status": "open",
            "additional_attributes": meta or {},
        }

        # Inclui a primeira mensagem na criação se fornecida
        if primeira_mensagem:
            payload["message"] = {"content": primeira_mensagem}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.BASE}/conversations", # <-- CORRIGIDO AQUI
                json=payload,
                headers=self.headers,         # <-- CORRIGIDO AQUI
            )
            if resp.status_code == 422:
                logger.error("Erro 422 conversa payload: %s", payload)
                logger.error("Motivo: %s", resp.text)
            resp.raise_for_status()
            conversation = resp.json()
            logger.info("Conversa criada: id=%s", conversation.get("id"))
            return conversation

    # ── Mensagens ─────────────────────────────────────────────────────────────

    async def send_message(
        self,
        conversation_id: int,
        message: str,
        message_type: str = "outgoing",
        private: bool = False,
    ) -> dict:
        """
        Envia uma mensagem na conversa.
        """
        payload = {
            "content": message,
            "message_type": message_type,
            "private": private,
            "content_type": "text",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.BASE}/conversations/{conversation_id}/messages", # <-- CORRIGIDO AQUI
                json=payload,
                headers=self.headers,                                    # <-- CORRIGIDO AQUI
            )
            resp.raise_for_status()
            return resp.json()

    async def add_private_note(self, conversation_id: int, note: str) -> dict:
        """
        Adiciona nota privada na conversa (visível só para agentes).
        """
        return await self.send_message(
            conversation_id=conversation_id,
            message=note,
            message_type="outgoing",
            private=True,
        )

    # ── Atribuição e labels ───────────────────────────────────────────────────

    async def assign_agent(self, conversation_id: int, agent_id: int) -> dict:
        """
        Atribui a conversa a um agente humano (handoff da IA).
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE}/conversations/{conversation_id}/assignments", # <-- CORRIGIDO AQUI
                json={"assignee_id": agent_id},
                headers=self.headers,                                       # <-- CORRIGIDO AQUI
            )
            resp.raise_for_status()
            return resp.json()

    async def assign_team(self, conversation_id: int, team_id: int) -> dict:
        """Atribui a conversa a um time (alternativa ao agent_id)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE}/conversations/{conversation_id}/assignments", # <-- CORRIGIDO AQUI
                json={"team_id": team_id},
                headers=self.headers,                                       # <-- CORRIGIDO AQUI
            )
            resp.raise_for_status()
            return resp.json()

    async def update_conversation_label(
        self, conversation_id: int, labels: list[str]
    ) -> dict:
        """
        Adiciona labels à conversa.
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE}/conversations/{conversation_id}/labels", # <-- CORRIGIDO AQUI
                json={"labels": labels},
                headers=self.headers,                                  # <-- CORRIGIDO AQUI
            )
            resp.raise_for_status()
            return resp.json()

    # ── Webhooks (registro programático) ─────────────────────────────────────

    async def register_webhook(self, url: str) -> dict:
        """
        Registra o webhook no Digiliza para receber eventos de mensagem.
        """
        payload = {
            "url": url,
            "subscriptions": ["message_created", "conversation_created"],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.BASE}/webhooks", # <-- CORRIGIDO AQUI
                json=payload,
                headers=self.headers,    # <-- CORRIGIDO AQUI
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Webhook registrado no Digiliza: id=%s url=%s", data.get("id"), url)
            return data





