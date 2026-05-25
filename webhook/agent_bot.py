import logging, os
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from webhook.digiliza import DigilizaClient
from webhook.qualifier import LeadQualifier

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter()
DEFAULT_AGENT_ID = int(os.getenv("EXACT_AGENT_ID", "1"))

@router.post("/webhook/agent-bot")
async def receive_agent_bot(request: Request, background_tasks: BackgroundTasks):
    try:
        event = await request.json()
    except Exception:
        return JSONResponse({"status": "payload invalido"}, status_code=400)

    logger.info("Agent Bot evento: %s", str(event)[:200])

    # Agent Bot so recebe mensagens incoming (do lead)
    message_type = event.get("message_type")
    if message_type != "incoming":
        return JSONResponse({"status": "ignorado"}, status_code=200)

    background_tasks.add_task(handle_bot_message, event)
    return JSONResponse({"status": "aceito"}, status_code=200)

async def handle_bot_message(event: dict):
    try:
        conversation_id = event.get("conversation", {}).get("id")
        contact = event.get("conversation", {}).get("meta", {}).get("sender", {})
        email = contact.get("email", "") or ""
        phone = contact.get("phone_number", "") or ""
        mensagem = event.get("content", "")

        if not mensagem or not conversation_id:
            return

        logger.info("Agent Bot mensagem conv %s: %s", conversation_id, mensagem[:60])

        qualifier = LeadQualifier()
        digiliza = DigilizaClient()

        # Primeira mensagem - inicializa a conversa
        state = qualifier.get_state(email or phone)
        if not state:
            lead = {
                "inbox_id": event.get("conversation", {}).get("inbox_id", 433),
                "name": contact.get("name", ""),
                "email": email,
                "phone_number": phone,
                "campanha": "",
                "assunto": "",
                "empresa": "",
            }
            primeira_msg = await qualifier.gerar_primeira_mensagem(lead)
            await digiliza.send_message(conversation_id, primeira_msg)
            return

        # Continua a conversa
        resposta_ia, acao = await qualifier.processar_resposta(
            email=email or phone,
            mensagem_lead=mensagem,
            conversation_id=conversation_id,
        )

        if acao:
            await _handle_acao(acao, qualifier, digiliza, conversation_id, email or phone)
        else:
            await digiliza.send_message(conversation_id, resposta_ia)

    except Exception as e:
        logger.exception("Erro no agent bot: %s", e)

async def _handle_acao(acao, qualifier, digiliza, conversation_id, email):
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