import os
import shutil
import logging
# Importamos a função que existe no seu projeto
from webhook.knowledge_base import indexar_manual

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Caminhos absolutos para não errar no Windows
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, "data")
    chroma_path = os.path.join(data_path, "chroma")

    # 1. Verifica se a pasta data existe
    if not os.path.exists(data_path):
        print(f"❌ Erro: A pasta {data_path} não existe!")
        return

    # 2. Limpa o banco antigo para a IA aprender tudo do zero
    if os.path.exists(chroma_path):
        print("🧹 Limpando memória antiga (chroma) para evitar duplicidade...")
        shutil.rmtree(chroma_path)

    # 3. Busca todos os arquivos PDF
    arquivos = [f for f in os.listdir(data_path) if f.endswith('.pdf')]
    
    if not arquivos:
        print("❌ Nenhum PDF encontrado na pasta ./data")
        return

    print(f"🚀 Encontrados {len(arquivos)} arquivos. Iniciando a 'quebra' das informações...")

    total_geral = 0
    for arquivo in arquivos:
        pdf_path = os.path.join(data_path, arquivo)
        print(f"\n--- 📄 Processando: {arquivo} ---")
        
        try:
            # Chama a sua função original para cada PDF
            # Ela vai ler, fatiar (chunking) e salvar no banco
            chunks = indexar_manual(pdf_path)
            print(f"✅ Sucesso! Geradas fatias para {arquivo}.")
            # Nota: O seu indexar_manual pode estar retornando o total acumulado
        except Exception as e:
            print(f"⚠️ Erro ao processar {arquivo}: {e}")

    print("\n✨ PROCESSO FINALIZADO!")
    print("Agora a IA já tem o Manual e a Apresentação 2026 na 'ponta da língua'.")

if __name__ == "__main__":
    main()