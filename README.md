# Gerenciador de Agendas com Flask e Google Calendar

Este projeto é uma aplicação web desenvolvida com Flask que permite aos usuários gerenciar seus eventos do Google Calendar. A aplicação utiliza o protocolo OAuth 2.0 para autenticação segura e acesso aos dados do usuário.

## Funcionalidades

- **Autenticação OAuth 2.0:** Login seguro com contas Google.
- **Listagem de Agendas:** Visualização de todas as agendas do usuário.
- **Visualização de Disponibilidade:** Exibição dos horários livres e ocupados para o dia corrente.
- **Gerenciamento de Eventos:**
    - Listagem dos próximos eventos de uma agenda.
    - Criação de novos eventos.
    - Exclusão de eventos existentes.
- **Interface Web:** Interface amigável para interação com as funcionalidades.

## Como Começar

### Pré-requisitos
- Python 3.11+
- Uma conta Google e o arquivo de credenciais OAuth (`client_secret.json`) baixado do Google Cloud Console.
- No console do Google Cloud, adicione o redirect URI que você for usar (exemplos abaixo) em “Authorized redirect URIs”.

### Instalação
1) Clone o repositório:
```bash
git clone <URL_DO_REPOSITORIO>
cd <NOME_DO_DIRETORIO>
```

2) Crie e ative o ambiente virtual  
- Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate
```
- Linux/macOS:
```bash
python -m venv .venv
source .venv/bin/activate
```

3) Instale as dependências:
```bash
pip install -r requirements.txt
```

4) Coloque o `client_secret.json` na raiz do projeto.

### Redirect URI
- Padrão local (recomendado): `http://127.0.0.1:5000/oauth2callback`
- Se precisar usar outro host/porta, defina a variável de ambiente `REDIRECT_URI` com o mesmo valor autorizado no Google Cloud.

### Rodando o servidor (dev)
- Windows (PowerShell):
```powershell
.\.venv\Scripts\Activate
$env:FLASK_APP="main.py"
flask run --host=127.0.0.1 --port=5000
```

- Linux/macOS:
```bash
source .venv/bin/activate
export FLASK_APP=main.py
flask run --host=127.0.0.1 --port=5000
```

Abra em `http://127.0.0.1:5000` e clique em “Autorizar com Google Calendar”.

## Estrutura do Projeto

```
.
├── main.py                # Lógica principal da aplicação Flask
├── requirements.txt       # Dependências do projeto
├── client_secret.json     # Credenciais da API (NÃO ENVIAR PARA O GIT)
├── devserver.sh           # Script (Linux/macOS) para iniciar o servidor
├── static/
│   └── styles.css         # Estilos da aplicação
└── templates/
    ├── base.html          # Layout base
    ├── index.html         # Página inicial
    ├── chat.html          # Chat principal
    └── error.html         # Página de erro
```

## Dependências

Principais dependências:
- Flask (servidor web)
- google-auth-oauthlib / google-api-python-client (OAuth + Google Calendar)
- python-dotenv, requests, python-dateutil, pytz
- openai, groq (LLM opcional para respostas inteligentes)

Veja a lista completa em `requirements.txt`.
