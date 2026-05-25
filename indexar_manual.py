"""
indexar_manual.py
Script para indexar o manual ICP da Magazord no ChromaDB.

Uso:
    python indexar_manual.py caminho/para/manual.pdf
    python indexar_manual.py  (usa o caminho padrão ./data/manual_icp.pdf)
"""
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    # Caminho do PDF
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = "./data/manual_icp.pdf"

    if not Path(pdf_path).exists():
        print(f"ERRO: Arquivo não encontrado: {pdf_path}")
        print()
        print("Uso: python indexar_manual.py caminho/para/manual.pdf")
        print("Ou coloque o PDF em: ./data/manual_icp.pdf")
        sys.exit(1)

    from webhook.knowledge_base import indexar_manual, status_base

    print(f"Indexando: {pdf_path}")
    total = indexar_manual(pdf_path)
    print(f"\n✓ {total} chunks indexados com sucesso!")

    stats = status_base()
    print(f"✓ Manual: {stats['chunks_manual']} chunks")
    print(f"✓ Histórico: {stats['conversas_historico']} conversas")
    print(f"✓ Banco salvo em: {stats['chroma_dir']}")


if __name__ == "__main__":
    main()
