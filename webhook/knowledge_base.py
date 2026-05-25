"""
webhook/knowledge_base.py
Sistema RAG para a Magazord:
- Indexa o manual de ICP em chunks semânticos
- Busca trechos relevantes baseado no perfil do lead
- Armazena conversas qualificadas para aprendizado
"""
import logging
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Diretorio para persistir o banco vetorial
CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_MANUAL = "magazord_icp"
COLLECTION_HISTORICO = "conversas_qualificadas"

_client = None
_col_manual = None
_col_historico = None


def _get_client():
    global _client
    if _client is None:
        import chromadb
        Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client


def _get_collections():
    global _col_manual, _col_historico
    client = _get_client()
    if _col_manual is None:
        _col_manual = client.get_or_create_collection(
            name=COLLECTION_MANUAL,
            metadata={"description": "Manual ICP Magazord"}
        )
    if _col_historico is None:
        _col_historico = client.get_or_create_collection(
            name=COLLECTION_HISTORICO,
            metadata={"description": "Historico de conversas qualificadas"}
        )
    return _col_manual, _col_historico


def indexar_manual(pdf_path: str) -> int:
    """
    Lê o PDF do manual ICP e indexa em chunks no ChromaDB.
    Retorna o número de chunks indexados.
    """
    import pypdf

    col_manual, _ = _get_collections()

    # Verifica se já foi indexado
   # if col_manual.count() > 0:
   #    logger.info("Manual já indexado com %d chunks.", col_manual.count())
   #    return col_manual.count()

    logger.info("Indexando manual ICP: %s", pdf_path)

    reader = pypdf.PdfReader(pdf_path)
    chunks = []
    ids = []
    metadatas = []

    # Extrai texto por página e divide em chunks
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if not text.strip():
            continue
        # Remove espaços duplos gerados por PDFs com formatação especial
        import re
        text = re.sub(r'  +', ' ', text)
        text = re.sub(r'\n +\n', '\n\n', text)

        # Divide por linhas e agrupa em chunks de ~300 chars
        linhas = [l.strip() for l in text.split("\n") if len(l.strip()) > 30]
        chunk_atual = ""
        chunk_idx = 0

        for linha in linhas:
            if len(chunk_atual) + len(linha) > 400 and chunk_atual:
                chunk_id = f"page_{i+1}_chunk_{chunk_idx}"
                chunks.append(chunk_atual.strip())
                ids.append(chunk_id)
                metadatas.append({
                    "pagina": i + 1,
                    "fonte": "Manual ICP Magazord v1.0"
                })
                chunk_atual = linha
                chunk_idx += 1
            else:
                chunk_atual += " " + linha

        # Adiciona o ultimo chunk da pagina
        if chunk_atual.strip():
            chunk_id = f"page_{i+1}_chunk_{chunk_idx}"
            chunks.append(chunk_atual.strip())
            ids.append(chunk_id)
            metadatas.append({
                "pagina": i + 1,
                "fonte": "Manual ICP Magazord v1.0"
            })

    if not chunks:
        logger.warning("Nenhum texto extraído do PDF.")
        return 0

    # Indexa em lotes de 50
    for i in range(0, len(chunks), 50):
        lote_chunks = chunks[i:i+50]
        lote_ids = ids[i:i+50]
        lote_meta = metadatas[i:i+50]
        col_manual.add(
            documents=lote_chunks,
            ids=lote_ids,
            metadatas=lote_meta,
        )

    logger.info("Manual indexado com sucesso: %d chunks.", len(chunks))
    return len(chunks)


def buscar_icp(query: str, n_resultados: int = 4) -> str:
    """
    Busca os trechos mais relevantes do manual ICP para a query.
    Retorna texto concatenado para incluir no prompt da IA.
    """
    col_manual, _ = _get_collections()

    if col_manual.count() == 0:
        logger.warning("Manual não indexado. Rode indexar_manual() primeiro.")
        return ""

    try:
        results = col_manual.query(
            query_texts=[query],
            n_results=min(n_resultados, col_manual.count()),
        )

        documentos = results.get("documents", [[]])[0]
        if not documentos:
            return ""

        contexto = "\n\n---\n\n".join(documentos)
        logger.debug("ICP encontrado: %d trechos para query '%s'", len(documentos), query[:50])
        return contexto

    except Exception as e:
        logger.warning("Erro ao buscar ICP: %s", e)
        return ""


def buscar_conversas_similares(perfil_lead: str, n_resultados: int = 3) -> str:
    """
    Busca conversas anteriores similares ao perfil do lead atual.
    Retorna exemplos de qualificações passadas para contexto.
    """
    _, col_historico = _get_collections()

    if col_historico.count() == 0:
        return ""

    try:
        results = col_historico.query(
            query_texts=[perfil_lead],
            n_results=min(n_resultados, col_historico.count()),
        )

        documentos = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documentos:
            return ""

        exemplos = []
        for doc, meta in zip(documentos, metadatas):
            score = meta.get("score", 0)
            resultado = meta.get("resultado", "")
            exemplos.append(f"[Score: {score} | Resultado: {resultado}]\n{doc}")

        return "\n\n---\n\n".join(exemplos)

    except Exception as e:
        logger.warning("Erro ao buscar conversas similares: %s", e)
        return ""


def salvar_conversa(
    email: str,
    perfil: str,
    resumo_conversa: str,
    score: int,
    resultado: str,  # "qualificado", "desqualificado", "transferido"
):
    """
    Salva uma conversa qualificada no banco para aprendizado futuro.
    """
    _, col_historico = _get_collections()

    try:
        doc_id = f"conv_{email}_{resultado}_{score}"
        texto = f"Perfil: {perfil}\nResumo: {resumo_conversa}"

        col_historico.upsert(
            documents=[texto],
            ids=[doc_id],
            metadatas=[{
                "email": email,
                "score": score,
                "resultado": resultado,
                "perfil": perfil[:200],
            }]
        )
        logger.info("Conversa salva no historico: %s | score=%d", resultado, score)

    except Exception as e:
        logger.warning("Erro ao salvar conversa: %s", e)


def status_base() -> dict:
    """Retorna estatísticas da base de conhecimento."""
    col_manual, col_historico = _get_collections()
    return {
        "chunks_manual": col_manual.count(),
        "conversas_historico": col_historico.count(),
        "chroma_dir": CHROMA_DIR,
    }
