import chromadb
import os

def inspecionar_tudo():
    path = "data/chroma"
    if not os.path.exists(path):
        print("❌ Pasta data/chroma não encontrada.")
        return

    client = chromadb.PersistentClient(path=path)
    colecoes = client.list_collections()
    
    print(f"🚀 Encontradas {len(colecoes)} coleções no banco.\n")

    for col in colecoes:
        collection = client.get_collection(name=col.name)
        contagem = collection.count()
        print(f"📦 Coleção: [{col.name}] | Total de fatias: {contagem}")
        
        if contagem > 0:
            print(f"--- Exemplos de 'quebra' em {col.name}: ---")
            # Busca os 3 primeiros pedaços de conhecimento
            dados = collection.get(limit=3)
            for i in range(len(dados['ids'])):
                print(f"\n📍 FATIA {i+1} (ID: {dados['ids'][i]}):")
                print(f"📝 CONTEÚDO: {dados['documents'][i][:350]}...")
                print("-" * 20)
        print("\n" + "="*40 + "\n")

if __name__ == "__main__":
    inspecionar_tudo()