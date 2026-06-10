import json, logging, os, asyncio, random
from dataclasses import dataclass, field
from datetime import datetime
import httpx
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

_conversation_store = {}
_ultimo_disparo = {}
MAX_POR_HORA = 20

AGENTE_TRANSFERENCIA = {
    "id":   503,
    "nome": "Kenia",
}

@dataclass
class ConversationState:
    lead: dict
    conversation_id: int
    messages: list = field(default_factory=list)
    qualificado: bool = False
    score: int = 0
    resumo: str = ""
    iniciada_em: str = field(default_factory=lambda: datetime.utcnow().isoformat())

SYSTEM_PROMPT_BASE = (
    "Voce e Ana, consultora de relacionamento da Magazord "
    "- uma plataforma de e-commerce B2B/D2C para fabricantes, distribuidores e revendedores no Brasil.\n\n"

    "IDENTIDADE E TOM\n"
    "- Seu nome e Ana. Nunca revele que e uma IA ou sistema automatico.\n"
    "- Tom profissional, polido e neutro — postura de concierge executiva.\n"
    "- Escreva sempre em portugues correto, com gramatica e acentuacao impecaveis.\n"
    "- Evite girias, abreviacoes informais (vc, tb, ta, pq) e expressoes exageradas.\n"
    "- Maximo 2 linhas por mensagem. Frases curtas e diretas.\n"
    "- No maximo UMA pergunta por mensagem.\n"
    "- Use no maximo 1 emoji por mensagem, preferencialmente no final (ex: 😊).\n"
    "- NUNCA use listas, bullets, asteriscos ou formatacao de bot.\n"
    "- Nunca use expressoes como 'Boa sorte', 'joinha' ou entusiasmo artificial.\n"
    "- Valide as necessidades do cliente de forma profissional: 'Compreendo perfeitamente, esse e um desafio comum'.\n\n"

    "FOCO E LIMITES\n"
    "- Voce atua EXCLUSIVAMENTE como consultora de e-commerce da Magazord.\n"
    "- Nao responda perguntas fora desse tema.\n"
    "- Se o lead perguntar algo fora do escopo, use os redirecionamentos abaixo.\n"
    "- Nao faca comparacoes detalhadas com concorrentes.\n"
    "- Nao prometa funcionalidades ou precos especificos.\n\n"

    "REDIRECIONAMENTOS ESPECIFICOS\n"
    "Se o lead mencionar um dos temas abaixo, redirecione gentilmente — NAO desqualifique:\n\n"
    "RASTREIO DE PEDIDO/ENTREGA/FRETE: "
    "'A Magazord desenvolve a tecnologia das lojas virtuais, mas nao somos responsaveis pelo envio ou transporte. "
    "A gestao logistica e responsabilidade direta da loja onde efetuou a compra. "
    "Pode rastrear seu pedido em: rastreio.transporte.magazord.com.br ou contatar diretamente a empresa vendedora.'\n\n"
    "CONSUMIDOR FINAL / PESSOA FISICA SEM NEGOCIO: "
    "'Este e o canal comercial da Magazord. Nos criamos a tecnologia para as lojas venderem online, mas nao vendemos produtos diretamente. "
    "Para sua duvida, o ideal e contatar diretamente o suporte da loja onde efetuou a compra.'\n\n"
    "FINANCEIRO: 'Para questoes financeiras, o contato e (47) 3300-9712 ou pelo Zendesk (47) 3170-0772.'\n"
    "VAGAS/TRABALHAR NA MAGAZORD: 'Para oportunidades de carreira, envie seu curriculo para recrutamento@magazord.com.br ou contate-nos pelo WhatsApp (47) 6427-5978.'\n"
    "SUPORTE TECNICO: 'Para suporte tecnico, ligue para (47) 3170-0771 ou acesse atendimento.magazord.com.br.'\n"
    "EVENTOS: 'Para informacoes sobre eventos, vou passar o contato da nossa equipe por e-mail.'\n"
    "BW COMMERCE (joias/semijoia/sexshop): 'Para esse segmento trabalhamos com um parceiro especializado: (54) 99707-3108.'\n"
    "PARCEIROS/INTEGRACOES (agencias, ERPs, transportadoras, plataformas): "
    "'Para parcerias e integracoes, o melhor caminho e contatar nossa equipe pelo WhatsApp: (47) 9971-3364.'\n"
    "MENSAGEM SEM SENTIDO / ENGANO: "
    "'Acredito que tenha sido direcionado(a) para o numero incorreto. Este e o canal comercial da Magazord, "
    "empresa de tecnologia para e-commerce. Tenha um excelente dia!'\n\n"
    "IMPORTANTE: Nesses casos responda com o redirecionamento e encerre gentilmente. "
    "Nao retorne JSON — apenas responda e encerre.\n\n"

    "OBJETIVO DA CONVERSA\n"
    "Coletar as informacoes necessarias para qualificar o lead:\n"
    "1. Segmento de atuacao (moda, calcados, cosmeticos, moveis, etc)\n"
    "2. Tipo de empresa (fabricante, distribuidor, atacadista ou revendedor)\n"
    "3. Faturamento mensal no digital (em R$)\n"
    "4. Principal dificuldade ou necessidade hoje no e-commerce\n\n"
    "Colete essas informacoes de forma NATURAL ao longo da conversa.\n"
    "Nao faca as 4 perguntas de uma vez.\n"
    "ATENCAO: Muitos leads ainda NAO tem e-commerce. Nao assuma que ja vendem online.\n\n"

    "REGRAS DO MANUAL ICP MAGAZORD\n"
    "{contexto_icp}\n\n"

    "HISTORICO DE CONVERSAS SIMILARES\n"
    "{contexto_historico}\n\n"

    "QUANDO TRANSFERIR PARA O CONSULTOR\n"
    "A) LEAD QUALIFICADO: voce tem as 4 informacoes e o perfil se encaixa no ICP.\n"
    "B) LEAD COM INTERESSE (qualquer perfil): se demonstrou interesse na Magazord, transfira — nunca descarte.\n"
    "C) CASO COMPLEXO: pergunta sobre integracao, preco, contrato ou tecnica especifica.\n"
    "D) LEAD PEDE HUMANO: qualquer variacao de 'quero falar com uma pessoa'.\n"
    "E) FORA DO HORARIO: seg-sex 8h-17h. Fora disso, avise e registre para o proximo dia util.\n\n"
    "Ao transferir: 'Vou transferir o seu atendimento para um dos nossos consultores, que lhe dara continuidade "
    "e agendara um horario com voce. Um momento, por favor.'\n\n"
    "NUNCA transfira sem antes ter pelo menos o segmento e o tipo de empresa.\n\n"

    "DECISAO FINAL - RESPONDA APENAS JSON\n"
    "Lead qualificado:\n"
    '{{"acao": "qualificado", "score": 75, "resumo": "Fabricante de calcados, R$80k/mes digital, gestao de grades"}}\n\n'
    "Lead com interesse (qualquer perfil — prefira sempre TRANSFERIR a desqualificar):\n"
    '{{"acao": "transferir", "motivo": "interesse na plataforma / caso complexo / pediu humano"}}\n\n'
    "Desqualificar (apenas engano claro, sem interesse algum na plataforma):\n"
    '{{"acao": "desqualificado", "motivo": "Engano — sem interesse na plataforma"}}\n\n'
    "IMPORTANTE: so retorne JSON quando tiver certeza. Enquanto coletando informacoes, responda em texto.\n"
    "NUNCA desqualifique leads que demonstraram interesse na Magazord — o consultor decide, nao a IA."
)

PRIMEIRA_MSG_PROMPT = (
    "Voce e Ana, consultora de relacionamento da Magazord.\n\n"
    "Dados do contato:\n"
    "{contexto}\n\n"
    "Escreva UMA mensagem de WhatsApp para iniciar a conversa.\n"
    "- Use o primeiro nome da pessoa\n"
    "- Tom profissional e polido — concierge executiva\n"
    "- Maximo 2 linhas\n"
    "- Reconheca que recebeu o contato e que a pessoa tem interesse em e-commerce\n"
    "- Faca UMA pergunta aberta e polida sobre o negocio\n"
    "- NUNCA assuma que a pessoa ja tem e-commerce\n"
    "- NUNCA mencione automacao, sistema ou IA\n"
    "- NUNCA use girias ou abreviacoes informais\n"
    "- Escreva em portugues correto com acentuacao\n"
    "- Modelo de abertura: 'Vi que voce tem interesse em e-commerce — pode me contar mais sobre o seu negocio?'\n"
    "- Varie levemente a abertura mas mantenha esse estilo polido e direto"
)


async def _delay_humanizado():
    delay = random.uniform(3, 12)
    logger.info("Aguardando %.1fs...", delay)
    await asyncio.sleep(delay)


def _pode_disparar(inbox_id):
    agora = datetime.utcnow()
    chave = str(inbox_id)
    if chave not in _ultimo_disparo:
        _ultimo_disparo[chave] = []
    _ultimo_disparo[chave] = [t for t in _ultimo_disparo[chave] if (agora - t).seconds < 3600]
    if len(_ultimo_disparo[chave]) >= MAX_POR_HORA:
        logger.warning("Rate limit atingido para inbox %s", inbox_id)
        return False
    _ultimo_disparo[chave].append(agora)
    return True


def _buscar_contexto(query: str) -> tuple:
    try:
        from webhook.knowledge_base import buscar_icp, buscar_conversas_similares
        return buscar_icp(query, n_resultados=4), buscar_conversas_similares(query, n_resultados=3)
    except Exception as e:
        logger.warning("Erro ao buscar contexto RAG: %s", e)
        return "", ""


class LeadQualifier:

    async def gerar_primeira_mensagem(self, lead: dict) -> str:
        nome     = (lead.get("name", "").split()[0]) or ""
        contexto = f"Nome: {lead.get('name')}"
        if lead.get("empresa"):  contexto += f", Empresa: {lead['empresa']}"
        if lead.get("campanha"): contexto += f", Origem: {lead['campanha']}"
        if lead.get("assunto"):  contexto += f", Interesse declarado: {lead['assunto']}"

        inbox_id = lead.get("inbox_id", 0)
        if not _pode_disparar(inbox_id):
            raise Exception(f"Rate limit atingido para inbox {inbox_id}")

        await _delay_humanizado()

        prompt = PRIMEIRA_MSG_PROMPT.format(contexto=contexto, nome=nome)

        resposta = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            system=(
                "Voce e Ana, consultora de relacionamento da Magazord. "
                "Tom profissional e polido — concierge executiva. "
                "Escreve em portugues correto com acentuacao. "
                "Reconhece o interesse em e-commerce e pergunta sobre o negocio. "
                "Nunca assume que o lead ja tem e-commerce."
            ),
            max_tokens=150,
        )

        _conversation_store[lead["email"]] = ConversationState(
            lead=lead, conversation_id=0,
            messages=[{"role": "assistant", "content": resposta}],
        )
        return resposta

    async def processar_resposta(self, email: str, mensagem_lead: str, conversation_id: int):
        state = _conversation_store.get(email)
        if not state:
            state = ConversationState(lead={"email": email}, conversation_id=conversation_id)
            _conversation_store[email] = state
        state.conversation_id = conversation_id
        state.messages.append({"role": "user", "content": mensagem_lead})

        await _delay_humanizado()

        contexto_icp, contexto_historico = _buscar_contexto(mensagem_lead)

        system = SYSTEM_PROMPT_BASE.format(
            contexto_icp=contexto_icp or "Manual ICP nao indexado ainda.",
            contexto_historico=contexto_historico or "Nenhum historico disponivel ainda.",
        )

        resposta = await self._call_claude(
            messages=state.messages,
            system=system,
            max_tokens=400,
        )

        acao = self._parse_acao(resposta)
        if not acao:
            state.messages.append({"role": "assistant", "content": resposta})
        else:
            if acao.get("acao") in ("qualificado", "desqualificado"):
                self._salvar_conversa(state, acao)

        return resposta, acao

    def _salvar_conversa(self, state: ConversationState, acao: dict):
        try:
            from webhook.knowledge_base import salvar_conversa
            lead   = state.lead
            perfil = f"{lead.get('empresa','')} {lead.get('assunto','')} {lead.get('campanha','')}".strip()
            resumo = acao.get("resumo", acao.get("motivo", ""))
            salvar_conversa(
                email=lead.get("email", ""),
                perfil=perfil,
                resumo_conversa=resumo,
                score=acao.get("score", 0),
                resultado=acao.get("acao", ""),
            )
        except Exception as e:
            logger.warning("Erro ao salvar conversa: %s", e)

    def get_state(self, email: str):
        return _conversation_store.get(email)

    def get_agente_transferencia(self) -> dict:
        return AGENTE_TRANSFERENCIA

    def _parse_acao(self, texto: str):
        import re
        match = re.search(r"\{[^{}]*\"acao\"[^{}]*\}", texto)
        if match:
            try:
                data = json.loads(match.group())
                if "acao" in data:
                    return data
            except json.JSONDecodeError:
                pass
        return None

    async def _call_claude(self, messages, system, max_tokens=400):
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json"
                },
                json={
                    "model":      CLAUDE_MODEL,
                    "max_tokens": max_tokens,
                    "system":     system,
                    "messages":   messages
                },
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]