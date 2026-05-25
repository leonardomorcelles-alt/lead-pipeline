import asyncio, logging, os
import httpx
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
_conversas_ia: dict = {}

def registrar_conversa(conversation_id: int):
    _conversas_ia[conversation_id] = 0
    logger.info("Conversa registrada para polling: id=%s", conversation_id)

async def iniciar_poller():
    logger.info("Poller iniciado. Intervalo: %ds", POLL_INTERVAL)
    while True:
        try:
            await _poll_conversas()
        except Exception as e:
            logger.exception("Erro no poller: %s", e)
        await asyncio.sleep(POLL_INTERVAL)

async def _poll_conversas():
    if not _conversas_ia:
        return
    from webhook.qualifier import LeadQualifier
    from webhook.digiliza import DigilizaClient
    base = os.getenv("DIGILIZA_API_URL") + "/api/v1/accounts/" + os.getenv("DIGILIZA_ACCOUNT_ID")
    headers = {"api_access_token": os.getenv("DIGILIZA_API_KEY")}
    for conv_id in list(_conversas_ia.keys()):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{base}/conversations/{conv_id}/messages", headers=headers)
                if r.status_code != 200:
                    continue
                data = r.json()
                messages = data.get("payload", [])
                ultima_id = _conversas_ia[conv_id]
                novas = [m for m in messages if m.get("message_type") == 0 and m.get("id", 0) > ultima_id]
                if not novas:
                    continue
                meta = data.get("meta", {})
                contact = meta.get("contact", {})
                email = contact.get("email", "") or ""
                phone = contact.get("phone_number", "") or ""
                qualifier = LeadQualifier()
                digiliza = DigilizaClient()
                for msg in sorted(novas, key=lambda m: m["id"]):
                    conteudo = msg.get("content", "")
                    if not conteudo:
                        continue
                    logger.info("Nova mensagem conv %s de %s: %s", conv_id, email or phone, conteudo[:60])
                    resposta_ia, acao = await qualifier.processar_resposta(
                        email=email or phone, mensagem_lead=conteudo, conversation_id=conv_id,
                    )
                    if acao:
                        await _handle_acao(acao, qualifier, digiliza, conv_id, email or phone)
                        if acao.get("acao") in ("qualificado", "desqualificado"):
                            _conversas_ia.pop(conv_id, None)
                    else:
                        await digiliza.send_message(conv_id, resposta_ia)
                    _conversas_ia[conv_id] = msg["id"]
        except Exception as e:
            logger.exception("Erro ao processar conv %s: %s", conv_id, e)

async def _handle_acao(acao, qualifier, digiliza, conversation_id, email):
    import httpx
    tipo = acao.get("acao")
    state = qualifier.get_state(email)
    agent_id = int(os.getenv("EXACT_AGENT_ID", "1"))
    if tipo == "qualificado":
        score = acao.get("score", 0)
        resumo = acao.get("resumo", "")
        logger.info("Lead QUALIFICADO: %s | score=%s", email, score)
        await digiliza.send_message(conversation_id, "Perfeito! Vou te conectar com nosso time agora. Um momento!")
        nota = f"*Resumo IA*\n\nScore: {score}/100\nResumo: {resumo}"
        await digiliza.add_private_note(conversation_id, nota)
        label = "qualificado-alto" if score >= 70 else "qualificado-medio"
        await digiliza.update_conversation_label(conversation_id, [label])
        await digiliza.assign_agent(conversation_id, agent_id)
    elif tipo == "desqualificado":
        await digiliza.update_conversation_label(conversation_id, ["desqualificado"])
        await digiliza.send_message(conversation_id, "Entendido! Qualquer duvida pode chamar. Ate mais!")
    elif tipo == "transferir":
        await digiliza.send_message(conversation_id, "Claro! Transferindo para um consultor agora.")
        await digiliza.assign_agent(conversation_id, agent_id)