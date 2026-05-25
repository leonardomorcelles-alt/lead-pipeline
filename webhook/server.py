import hmac, logging, os
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from webhook.digiliza import DigilizaClient
from webhook.qualifier import LeadQualifier
from webhook import reply_handler
from webhook import agent_bot

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Lead Pipeline Webhook", version="1.0.0")
app.include_router(reply_handler.router)
app.include_router(agent_bot.router)


ZOHO_WEBHOOK_TOKEN = os.getenv("ZOHO_WEBHOOK_TOKEN", "")

def verify_zoho_token(authorization: str) -> bool:
    if not ZOHO_WEBHOOK_TOKEN:
        return True
    return hmac.compare_digest(authorization or "", f"Bearer {ZOHO_WEBHOOK_TOKEN}")

@app.post("/webhook/zoho-lead")
async def receive_zoho_lead(request: Request, background_tasks: BackgroundTasks, authorization: str = Header(default="")):
    if not verify_zoho_token(authorization):
        raise HTTPException(status_code=401, detail="Token invalido")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload invalido")
    logger.info("Lead recebido: %s", payload.get("email"))
    logger.info("Payload completo: %s", payload)
    background_tasks.add_task(process_lead, payload)
    return JSONResponse({"status": "aceito"}, status_code=200)

@app.get("/health")
async def health():
    return {"status": "ok"}

async def process_lead(payload: dict):
    lead = normalize_payload(payload)
    logger.info("Processando: %s | %s", lead["name"], lead["email"])
    logger.info("ACCOUNT_ID em uso: %s", os.getenv("DIGILIZA_ACCOUNT_ID"))
    digiliza = DigilizaClient()
    qualifier = LeadQualifier()
    try:
        contact = await digiliza.upsert_contact(lead)
        contact_id = contact["id"]
        logger.info("Contato Digiliza: id=%s", contact_id)
        
        primeira_msg = await qualifier.gerar_primeira_mensagem(lead)
        
        # Cria a conversa no Digiliza
        conversation = await digiliza.create_conversation(
            contact_id=contact_id,
            inbox_id=lead["inbox_id"],
            phone_number=lead["phone_number"],
            meta={"campanha": lead.get("campanha", ""), "utm_source": lead.get("utm_source", "")},
            primeira_mensagem=primeira_msg,
        )
        
        conversation_id = conversation["id"]
        logger.info("Conversa criada: id=%s -> %s", conversation_id, lead["phone_number"])
        
        # =====================================================================
        # 1. Atribui imediatamente ao Agente Bot IA (ID 260)
        # Isso impede que o bot nativo "Kenia e Mazo" (ID 106) assuma o lead
        # =====================================================================
        await digiliza.assign_agent(conversation_id, 260)
        logger.info("Conversa %s blindada e atribuída à IA (ID 260)", conversation_id)

        # =====================================================================
        # 2. Garante a label "ia-ativa" para o reply_handler saber que deve atuar
        # (Caso isso já não esteja sendo feito dentro do create_conversation)
        # =====================================================================
        await digiliza.update_conversation_label(conversation_id, ["ia-ativa"])

    except Exception as e:
        logger.exception("Erro ao processar lead %s: %s", lead.get("email"), e)

def normalize_payload(raw: dict) -> dict:
    # Zoho envia dados reais dentro de contact_data[0]
    cd = {}
    if raw.get("contact_data") and len(raw["contact_data"]) > 0:
        cd = raw["contact_data"][0]
    
    name = cd.get("firstname", "") + " " + cd.get("lastname", "")
    name = name.strip() or cd.get("Nome_completo", "") or raw.get("name", "")
    email = cd.get("contact_email") or cd.get("work_email") or raw.get("email", "")
    phone = cd.get("mobile") or cd.get("phone") or raw.get("phone_number", "")

    return {
        "inbox_id":     int(raw.get("inbox_id", 1)),
        "name":         name.strip(),
        "email":        email.lower().strip(),
        "phone_number": _format_phone(phone),
        "campanha":     cd.get("cf_utm_campaign", ""),
        "utm_source":   cd.get("cf_utm_source", ""),
        "utm_medium":   cd.get("cf_utm_medium", ""),
        "cidade":       cd.get("city", ""),
        "empresa":      cd.get("companyname", ""),
        "assunto":      cd.get("Selecione_o_assunto", ""),
    }

def _format_phone(phone: str) -> str:
    if not phone: return ""
    digits = "".join(c for c in phone if c.isdigit())
    if not digits.startswith("55"): digits = "55" + digits
    # Remove digito extra apos o codigo do pais (55)
    # Formato correto: 55 + DDD (2) + numero (8 ou 9) = 12 ou 13 digitos
    if len(digits) > 13:
        digits = digits[:2] + digits[3:]
    return "+" + digits







