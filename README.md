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

- Python 3.11 ou superior
- Conta do Google e credenciais da API do Google Calendar (`client_secret.json`)

### Instalação

1.  **Clone o repositório:**
    ```bash
    git clone <URL_DO_REPOSITORIO>
    cd <NOME_DO_DIRETORIO>
    ```

2.  **Crie e ative um ambiente virtual:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure as credenciais:**
    - Renomeie seu arquivo de credenciais da API do Google para `client_secret.json` e coloque-o na raiz do projeto.

### Executando o Servidor

Para iniciar o servidor de desenvolvimento, execute:

```bash
./devserver.sh
```

A aplicação estará disponível em `http://localhost:5000`.

## Estrutura do Projeto

```
.
├── main.py                # Lógica principal da aplicação Flask
├── requirements.txt         # Dependências do projeto
├── client_secret.json       # Credenciais da API (NÃO ENVIAR PARA O GIT)
├── devserver.sh             # Script para iniciar o servidor
├── static/
│   └── style.css            # Estilos da aplicação
└── templates/
    ├── base.html            # Layout base
    ├── index.html           # Página inicial
    ├── calendars.html       # Lista de agendas
    ├── events.html          # Lista de eventos de uma agenda
    ├── create_event.html    # Formulário para criar evento
    └── error.html           # Página de erro
```

## Dependências

As principais dependências do projeto são:

- **Flask:** Micro-framework web.
- **google-auth-oauthlib:** Suporte para OAuth 2.0 com o Google.
- **google-api-python-client:** Biblioteca cliente para as APIs do Google.
- **python-dateutil:** Utilitários para manipulação de datas.

Todas as dependências estão listadas no arquivo `requirements.txt`.
