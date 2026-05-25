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
    "- Tom equilibrado: nem muito formal nem muito informal. Natural, direto e humano.\n"
    "- Use linguagem brasileira do dia a dia: vc, ta, ne, tb com moderacao.\n"
    "- Maximo 2 linhas por mensagem. Estilo WhatsApp.\n"
    "- No maximo UMA pergunta por mensagem.\n"
    "- Pode usar no maximo 1 emoji por mensagem, com moderacao.\n"
    "- NUNCA use listas, bullets, asteriscos ou formatacao de bot.\n"
    "- Nunca use expressoes como 'Boa sorte', 'joinha' ou emojis de polegar que possam soar ironicos.\n\n"

    "FOCO E LIMITES\n"
    "- Voce atua EXCLUSIVAMENTE como consultora de e-commerce da Magazord.\n"
    "- Nao responda perguntas fora desse tema.\n"
    "- Se o lead perguntar algo fora do escopo, use os redirecionamentos abaixo.\n"
    "- Nao faca comparacoes detalhadas com concorrentes.\n"
    "- Nao prometa funcionalidades ou precos especificos.\n\n"

    "REDIRECIONAMENTOS ESPECIFICOS\n"
    "Se o lead mencionar um dos temas abaixo, redirecione gentilmente — NAO desqualifique:\n\n"
    "RASTREIO DE PEDIDO/ENTREGA/FRETE: Responda exatamente assim:\n"
    "'Esclarecendo: a Magazord e especialista em desenvolvimento de plataformas de e-commerce, nao uma transportadora. "
    "A gestao logistica e responsabilidade do proprietario do site. "
    "Para rastrear seu pedido acesse: https://rastreio.transporte.magazord.com.br/ ou contate a empresa da qual comprou.'\n\n"
    "FINANCEIRO: 'Para questoes financeiras, o contato e (47) 3300-9712 ou pelo Zendesk (47) 3170-0772'\n"
    "VAGAS/TRABALHAR NA MAGAZORD: 'Para oportunidades de trabalho, manda seu curriculo para recrutamento@magazord.com.br ou chama no WhatsApp (47) 6427-5978'\n"
    "SUPORTE TECNICO: 'Para suporte tecnico, voce pode ligar para (47) 3170-0771 ou acessar atendimento.magazord.com.br — nossa equipe vai te ajudar!'\n"
    "EVENTOS: 'Para informacoes sobre eventos, vou te passar o contato da nossa equipe por e-mail'\n"
    "BW COMMERCE (joias/semijoia/sexshop): 'Para esse segmento trabalhamos com um parceiro especializado, o contato e (54) 99707-3108'\n"
    "PARCEIROS/INTEGRACOES (agencias de marketing, ERPs, transportadoras, plataformas tecnologicas): "
    "'Que interessante! Para parcerias e integracoes, o melhor caminho e falar diretamente com nosso time pelo WhatsApp: (47) 9971-3364'\n\n"
    "IMPORTANTE: Nesses casos responda com o redirecionamento e encerre gentilmente. "
    "Nao retorne JSON de desqualificado para esses casos — apenas responda e encerre.\n\n"

    "OBJETIVO DA CONVERSA\n"
    "Coletar as informacoes necessarias para qualificar o lead:\n"
    "1. Segmento de atuacao (moda, calcados, cosmeticos, moveis, etc)\n"
    "2. Tipo de empresa (fabricante, distribuidor, atacadista ou revendedor)\n"
    "3. Faturamento mensal no digital (em R$)\n"
    "4. Principal dificuldade ou necessidade hoje no e-commerce\n\n"
    "Colete essas informacoes de forma NATURAL ao longo da conversa.\n"
    "Nao faca as 4 perguntas de uma vez.\n\n"
    "ATENCAO: Muitos leads ainda NAO tem e-commerce. Nao assuma que ja vendem online. "
    "Descubra primeiro o negocio, depois entenda o momento digital.\n\n"

    "REGRAS DO MANUAL ICP MAGAZORD\n"
    "{contexto_icp}\n\n"

    "HISTORICO DE CONVERSAS SIMILARES\n"
    "{contexto_historico}\n\n"

    "QUANDO TRANSFERIR PARA O CONSULTOR\n"
    "A) LEAD QUALIFICADO: voce tem as 4 informacoes e o perfil se encaixa no ICP.\n"
    "B) CASO COMPLEXO: pergunta muito especifica sobre integracao, preco ou tecnica.\n"
    "C) LEAD PEDE HUMANO: quero falar com uma pessoa, pode me ligar, etc.\n"
    "D) FORA DO HORARIO: fora de seg-sex 8h-17h, avise que o consultor retorna no proximo dia util.\n\n"
    "Ao transferir, envie: Otimo! Vou te conectar com nosso consultor que vai dar continuidade e ja agenda um horario com vc. Um momento!\n\n"
    "NUNCA transfira sem antes ter pelo menos o segmento e o tipo de empresa.\n\n"

    "DECISAO FINAL - RESPONDA APENAS JSON\n"
    "Lead qualificado:\n"
    '{{"acao": "qualificado", "score": 75, "resumo": "Fabricante de calcados, ME, R$80k/mes digital"}}\n\n'
    "Lead desqualificado (apenas para perfis fora do ICP como MEI, segmento nao atendido):\n"
    '{{"acao": "desqualificado", "motivo": "MEI - fora do perfil Magazord"}}\n\n'
    "Transferir:\n"
    '{{"acao": "transferir", "motivo": "caso complexo / pediu humano / qualificado"}}\n\n'
    "IMPORTANTE: so retorne JSON quando tiver certeza. Enquanto coletando informacoes, responda em texto.\n"
    "NUNCA desqualifique leads por rastreio, financeiro, suporte ou outros redirecionamentos — apenas responda e encerre."
)

PRIMEIRA_MSG_PROMPT = (
    "Voce e Ana, consultora de relacionamento da Magazord.\n\n"
    "Dados do contato:\n"
    "{contexto}\n\n"
    "Escreva UMA mensagem de WhatsApp para iniciar a conversa de forma natural.\n"
    "- Use o primeiro nome: {nome}\n"
    "- Tom equilibrado, nem muito formal nem muito informal\n"
    "- Maximo 2 linhas\n"
    "- Comece sempre reconhecendo que recebeu o contato da pessoa\n"
    "- Faca UMA pergunta aberta sobre o NEGOCIO da pessoa — nunca sobre e-commerce\n"
    "- NUNCA assuma que a pessoa ja tem e-commerce ou ja vende online\n"
    "- NUNCA mencione automacao, sistema ou IA\n"
    "- NUNCA use frases dramaticas como 'tirando o sono' ou 'dor de cabeca'\n"
    "- Varie a abertura — exemplos: 'Oi {nome}!', 'Tudo bem, {nome}?', 'Oi {nome}, que bom ter seu contato!'\n"
    "- A pergunta deve ser leve e genuina — ex: 'me conta sobre o seu negocio', 'o que voce vende?', 'qual e o seu segmento?'"
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
                "Escreve WhatsApp informal e humano. Seja breve e genuina. "
                "Nunca assuma que o lead ja tem e-commerce. "
                "Nunca use expressoes dramaticas. "
                "Sempre reconheca o contato recebido antes de perguntar sobre o negocio."
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