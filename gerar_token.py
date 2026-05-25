import requests

def gerar_tokens_zoho():
    url = "https://accounts.zoho.com/oauth/v2/token"

    # ⚠️ IMPORTANTE: Você precisa gerar um código novo no navegador e colar aqui dentro das aspas!
    # Link para gerar: https://accounts.zoho.com/oauth/v2/auth?scope=ZohoMarketingAutomation.lead.ALL,ZohoMarketingAutomation.campaign.ALL&client_id=1000.EWC93AXB8FYU5ANTJ6M64N0OXEEECX&response_type=code&access_type=offline&prompt=consent&redirect_uri=https://chat.digiliza.com
    codigo_novo = "COLE_SEU_CODIGO_FRESQUINHO_AQUI"

    payload = {
        "grant_type": "authorization_code",
        "client_id": "1000.EWC93AXB8FYU5ANTJ6M64N0OXEEECX",
        "client_secret": "af39f347d86d5dd93e0b9ff9f98b8d5dd98e835ef4",
        "redirect_uri": "https://chat.digiliza.com",
"code": "1000.2f0a3faa2da34e143cf24835e7aa57c8.f5aecc71db70dc99a20da5911a050201"    }

    print("Fazendo requisição para o Zoho...")
    response = requests.post(url, data=payload)
    dados = response.json()

    if "error" in dados:
        print("\n❌ ERRO DO ZOHO:", dados["error"])
        if dados["error"] == "invalid_code":
            print("💡 Motivo: O seu código expirou. Copie aquele link gigante, cole no navegador de novo, pegue o novo código e atualize a variável 'codigo_novo' aqui no script!")
    else:
        print("\n✅ SUCESSO! Copie as chaves abaixo para o seu arquivo .env:")
        print("-" * 50)
        print(f"ZOHO_ACCESS_TOKEN={dados.get('access_token')}")
        print(f"ZOHO_REFRESH_TOKEN={dados.get('refresh_token')}")
        print("-" * 50)

if __name__ == "__main__":
    gerar_tokens_zoho()