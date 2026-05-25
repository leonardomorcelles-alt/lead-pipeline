import asyncio, logging, os
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from webhook.digiliza import DigilizaClient
from webhook.qualifier import LeadQualifier, _conversation_store

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter()

SENDGRID_API_KEY   = os.getenv("SENDGRID_API_KEY", "")
GMAIL_REMETENTE    = os.getenv("GMAIL_REMETENTE", "")
GMAIL_DESTINATARIO = os.getenv("GMAIL_DESTINATARIO", "")
DIGILIZA_URL       = os.getenv("DIGILIZA_API_URL", "https://chat.digiliza.com")
ACCOUNT_ID         = os.getenv("DIGILIZA_ACCOUNT_ID", "132")

_debounce_buffer: dict = {}
_debounce_delay = 4.0


@router.post("/webhook/digiliza-reply")
async def receive_digiliza_reply(request: Request, background_tasks: BackgroundTasks):
    try:
        event = await request.json()
    except Exception:
        return JSONResponse({"status": "payload invalido"}, status_code=400)
    if event.get("message_type") != "incoming":
        return JSONResponse({"status": "ignorado"}, status_code=200)
    labels = event.get("conversation", {}).get("labels", [])
    if "ia-ativa" not in labels:
        return JSONResponse({"status": "ignorado - sem label ia-ativa"}, status_code=200)
    background_tasks.add_task(handle_reply_debounced, event)
    return JSONResponse({"status": "aceito"}, status_code=200)


async def handle_reply_debounced(event: dict):
    conversation_id = event["conversation"]["id"]
    chave = str(conversation_id)
    mensagem = event.get("content", "")
    if not mensagem:
        return
    if chave not in _debounce_buffer:
        _debounce_buffer[chave] = {"mensagens": [], "event": event}
    _debounce_buffer[chave]["mensagens"].append(mensagem)
    await asyncio.sleep(_debounce_delay)
    buffer = _debounce_buffer.get(chave, {})
    if not buffer:
        return
    mensagens = buffer.get("mensagens", [])
    _debounce_buffer.pop(chave, None)
    mensagem_final = " ".join(mensagens)
    ultimo_event = dict(event)
    ultimo_event["content"] = mensagem_final
    await handle_reply(ultimo_event)


async def handle_reply(event: dict):
    try:
        conversation_id = event["conversation"]["id"]
        contact  = event["conversation"]["meta"]["sender"]
        email    = contact.get("email", "")
        phone    = contact.get("phone_number", "")
        mensagem = event.get("content", "")
        if not mensagem:
            return

        qualifier = LeadQualifier()
        digiliza  = DigilizaClient()

        # Gatilho para reiniciar atendimento
        if mensagem.strip().lower() == "/endnew":
            logger.info("Gatilho /endnew — reiniciando atendimento para %s", email or phone)
            chave = email or phone
            if chave in _conversation_store:
                del _conversation_store[chave]
            await digiliza.update_conversation_label(conversation_id, ["ia-ativa"])
            lead_novo = {
                "inbox_id":     event["conversation"].get("inbox_id", 433),
                "name":         contact.get("name", ""),
                "email":        email or phone,
                "phone_number": phone,
                "empresa": "", "campanha": "", "assunto": "",
            }
            nova_msg = await qualifier.gerar_primeira_mensagem(lead_novo)
            await digiliza.send_message(conversation_id, nova_msg)
            return

        logger.info("Resposta de %s (conv %s): %s", email or phone, conversation_id, mensagem[:60])

        resposta_ia, acao = await qualifier.processar_resposta(
            email=email or phone,
            mensagem_lead=mensagem,
            conversation_id=conversation_id,
        )
        if acao:
            await _handle_acao(acao, qualifier, digiliza, conversation_id, email or phone)
        else:
            await digiliza.send_message(conversation_id=conversation_id, message=resposta_ia)

    except Exception as e:
        logger.exception("Erro ao processar resposta: %s", e)


async def _handle_acao(acao, qualifier, digiliza, conversation_id, email):
    tipo     = acao.get("acao")
    state    = qualifier.get_state(email)
    agente   = qualifier.get_agente_transferencia()
    agent_id = agente["id"]

    if tipo == "qualificado":
        score  = acao.get("score", 0)
        resumo = acao.get("resumo", "")
        logger.info("Lead QUALIFICADO: %s | score=%s", email, score)
        await digiliza.send_message(
            conversation_id,
            "Otimo! Vou te conectar com nosso consultor que vai dar continuidade e ja agenda um horario com vc. Um momento!"
        )
        nota = (
            f"*Resumo IA*\n\n"
            f"Score: {score}/100\n"
            f"Resumo: {resumo}\n"
            f"Campanha: {state.lead.get('campanha','') if state else ''}"
        )
        await digiliza.add_private_note(conversation_id, nota)
        label = "qualificado-alto" if score >= 70 else "qualificado-medio"
        await digiliza.update_conversation_label(conversation_id, [label])
        await digiliza.assign_agent(conversation_id, agent_id)
        _enviar_email_sendgrid(
            lead_email=email, state=state, score=score,
            resumo=resumo, conversation_id=conversation_id, tipo="qualificado"
        )
        if state:
            await _send_to_exact_sales(state.lead, score, resumo)

    elif tipo == "desqualificado":
        motivo = acao.get("motivo", "")
        logger.info("Lead DESQUALIFICADO: %s | motivo=%s", email, motivo)
        await digiliza.update_conversation_label(conversation_id, ["desqualificado"])
        await digiliza.send_message(
            conversation_id,
            "Que bom ter conversado! Por enquanto nossa plataforma pode ser um pouco além do que você precisa agora, mas isso é ótimo — significa que você está no caminho certo 😊"
        )
        await asyncio.sleep(2)
        await digiliza.send_message(
            conversation_id,
            "No nosso blog tem muito conteúdo que pode te ajudar nessa jornada: magazord.com.br/blog — qualquer dúvida é só chamar!"
        )

    elif tipo == "transferir":
        motivo = acao.get("motivo", "")
        logger.info("Lead TRANSFERIDO: %s | motivo=%s", email, motivo)
        await digiliza.send_message(
            conversation_id,
            "Otimo! Vou te conectar com nosso consultor que vai dar continuidade e ja agenda um horario com vc. Um momento!"
        )
        await digiliza.update_conversation_label(conversation_id, ["transferido"])
        await digiliza.assign_agent(conversation_id, agent_id)
        _enviar_email_sendgrid(
            lead_email=email, state=state, score=0,
            resumo=motivo, conversation_id=conversation_id, tipo="transferir"
        )


def _enviar_email_sendgrid(lead_email, state, score, resumo, conversation_id, tipo):
    if not SENDGRID_API_KEY or not GMAIL_REMETENTE or not GMAIL_DESTINATARIO:
        logger.warning("SendGrid nao configurado — pulando envio de e-mail.")
        return
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        lead      = state.lead if state else {}
        nome      = lead.get("name", "Nao identificado")
        empresa   = lead.get("empresa", "Nao identificado")
        campanha  = lead.get("campanha", "-")
        assunto   = lead.get("assunto", "-")
        telefone  = lead.get("phone_number", "-")
        link_conv = f"{DIGILIZA_URL}/app/accounts/{ACCOUNT_ID}/conversations/{conversation_id}"
        if tipo == "qualificado":
            label_status  = "QUALIFICADO"
            cor_status    = "#1e8e3e"
            score_txt     = f" &mdash; Score: {score}/100"
            assunto_email = f"[QUALIFICADO] Lead - {empresa}"
        else:
            label_status  = "TRANSFERIDO"
            cor_status    = "#1a73e8"
            score_txt     = ""
            assunto_email = f"[TRANSFERIDO] Lead - {empresa}"
        corpo_html = f"""<html><body style="font-family:Arial,sans-serif;color:#202124;max-width:600px;margin:0 auto;">
<div style="background:#1a73e8;padding:20px;border-radius:8px 8px 0 0;">
  <h2 style="color:white;margin:0;">Magazord - IA de Atendimento</h2>
  <p style="color:#e8f0fe;margin:4px 0 0 0;">Novo lead para seu atendimento</p>
</div>
<div style="background:#f8f9fa;padding:20px;border-radius:0 0 8px 8px;border:1px solid #dadce0;">
  <div style="background:{cor_status};color:white;padding:8px 16px;border-radius:4px;display:inline-block;margin-bottom:16px;">
    <strong>{label_status}</strong>{score_txt}
  </div>
  <table style="width:100%;border-collapse:collapse;">
    <tr><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;width:35%;">Nome</td><td style="padding:10px;border:1px solid #dadce0;">{nome}</td></tr>
    <tr style="background:#f8f9fa;"><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;">Empresa</td><td style="padding:10px;border:1px solid #dadce0;">{empresa}</td></tr>
    <tr><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;">E-mail</td><td style="padding:10px;border:1px solid #dadce0;">{lead_email}</td></tr>
    <tr style="background:#f8f9fa;"><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;">Telefone</td><td style="padding:10px;border:1px solid #dadce0;">{telefone}</td></tr>
    <tr><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;">Interesse</td><td style="padding:10px;border:1px solid #dadce0;">{assunto}</td></tr>
    <tr style="background:#f8f9fa;"><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;">Campanha</td><td style="padding:10px;border:1px solid #dadce0;">{campanha}</td></tr>
    <tr><td style="padding:10px;border:1px solid #dadce0;font-weight:bold;">Resumo IA</td><td style="padding:10px;border:1px solid #dadce0;">{resumo}</td></tr>
  </table>
  <div style="margin-top:20px;text-align:center;">
    <a href="{link_conv}" style="background:#1a73e8;color:white;padding:12px 24px;border-radius:4px;text-decoration:none;font-weight:bold;display:inline-block;">Ver conversa no Digiliza</a>
  </div>
  <p style="color:#5f6368;font-size:12px;margin-top:20px;text-align:center;">Enviado automaticamente pela IA de Atendimento da Magazord</p>
</div>
</body></html>"""
        msg = Mail(
            from_email=GMAIL_REMETENTE,
            to_emails=GMAIL_DESTINATARIO,
            subject=assunto_email,
            html_content=corpo_html
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        r  = sg.send(msg)
        logger.info("E-mail enviado via SendGrid para %s — status %s", GMAIL_DESTINATARIO, r.status_code)
    except Exception as e:
        logger.error("Erro ao enviar e-mail SendGrid: %s", e)


async def _send_to_exact_sales(lead, score, resumo):
    import httpx
    exact_url   = os.getenv("EXACT_API_URL", "")
    exact_token = os.getenv("EXACT_TOKEN", "")
    if not exact_url or not exact_token:
        return
    payload = {
        "name":  lead.get("name", ""),
        "email": lead.get("email", ""),
        "phone": lead.get("phone_number", ""),
        "score": score,
        "notes": resumo,
        "custom_fields": {
            "campanha": lead.get("campanha", ""),
            "origem":   "whatsapp_ia",
        },
    }
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.post(
                f"{exact_url}/leads",
                json=payload,
                headers={"X-Auth-Token": exact_token}
            )
            r.raise_for_status()
            logger.info("Lead enviado ao Exact Sales: %s", lead.get("email"))
        except Exception as e:
            logger.error("Falha Exact Sales: %s", e)
