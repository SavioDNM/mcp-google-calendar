
import os
import json
import secrets
from datetime import datetime, timedelta
import re
from flask import Flask, redirect, url_for, request, render_template, jsonify, session
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from openai import OpenAI
from groq import Groq
from dateutil import parser
import pytz

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

# --- LLM & Timezone Configuration ---
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TIMEZONE = 'America/Sao_Paulo'

# --- Persistent Cache for OAuth State & Credentials ---
CACHE_FILE = '/tmp/persistent_cache.json'

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

# --- Google Calendar API Service ---
def get_calendar_service(credentials_info):
    credentials = Credentials(**credentials_info)
    return build('calendar', 'v3', credentials=credentials)

# --- FINALIZED TOOL ARCHITECTURE ---

def list_calendars(service):
    try:
        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get('items', [])
        if not calendars:
            return {"success": True, "count": 0, "calendars": []}
        
        formatted_calendars = [
            {"id": cal['id'], "name": cal['summary'], "primary": cal.get('primary', False)}
            for cal in calendars
        ]
        return {"success": True, "count": len(formatted_calendars), "calendars": formatted_calendars}
    except HttpError as e:
        return {"error": f"An error occurred: {e}"}

def search_events(service, query=None, calendar_name=None, date_filter=None, days_ahead=7):
    try:
        calendar_id = 'primary'
        if calendar_name and calendar_name.lower() != 'primary':
            calendars_result = service.calendarList().list().execute()
            calendars = calendars_result.get('items', [])
            found_calendar = next((cal for cal in calendars if cal['summary'].lower() == calendar_name.lower()), None)
            if found_calendar:
                calendar_id = found_calendar['id']
            else:
                return {"error": f"Agenda '{calendar_name}' não encontrada."}

        tz = pytz.timezone(TIMEZONE)
        if date_filter:
            start_dt = tz.localize(datetime.strptime(date_filter, '%Y-%m-%d').replace(hour=0, minute=0, second=0))
            end_dt = start_dt + timedelta(days=1)
            time_min = start_dt.isoformat()
            time_max = end_dt.isoformat()
        else:
            now = datetime.now(tz)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()

        events_result = service.events().list(
            calendarId=calendar_id, 
            timeMin=time_min, 
            timeMax=time_max, 
            q=query, 
            singleEvents=True, 
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        if not events:
            return {"found": False, "message": f"Nenhum evento encontrado com os critérios fornecidos na agenda '{calendar_name or 'principal'}'"}

        results = []
        for event in events:
            results.append({
                "event_id": event['id'],
                "title": event.get('summary', 'Sem título'),
                "start": event['start'].get('dateTime', event['start'].get('date')),
                "end": event['end'].get('dateTime', event['end'].get('date')),
                "calendar_id": calendar_id
            })
        return {"found": True, "count": len(results), "events": results}
    except HttpError as e:
        return {"error": f"An error occurred: {e}"}

def modify_calendar_event(service, event_id, calendar_id, action, new_title=None, new_date=None, new_start_time=None, new_duration_hours=None):
    try:
        if new_duration_hours == "" or new_duration_hours == "0": new_duration_hours = None
        if new_title == "": new_title = None
        if new_date == "": new_date = None
        if new_start_time == "": new_start_time = None

        if action.lower() == "delete":
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return {"success": True, "action": "deleted", "message": f"Evento {event_id} deletado com sucesso"}
        
        elif action.lower() == "update":
            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            if new_title: event['summary'] = new_title
            if new_date and new_start_time:
                tz = pytz.timezone(TIMEZONE)
                start_dt = tz.localize(datetime.strptime(f"{new_date} {new_start_time}", "%Y-%m-%d %H:%M"))
                duration = float(new_duration_hours) if new_duration_hours else 1
                end_dt = start_dt + timedelta(hours=duration)
                event['start'] = {'dateTime': start_dt.isoformat(), 'timeZone': TIMEZONE}
                event['end'] = {'dateTime': end_dt.isoformat(), 'timeZone': TIMEZONE}

            updated_event = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
            return {"success": True, "action": "updated", "event_id": event_id, "title": updated_event.get('summary'), "link": updated_event.get('htmlLink')}
        else:
            return {"error": "Ação deve ser 'update' ou 'delete'"}
    except HttpError as e:
        return {"error": f"An error occurred: {e}"}

def smart_schedule_event(service, title, preferred_date, preferred_time, calendar_name=None, duration_hours=1, description="", check_conflicts=True):
    try:
        calendar_id = 'primary'
        if calendar_name and calendar_name.lower() != 'primary':
            calendars_result = service.calendarList().list().execute()
            calendars = calendars_result.get('items', [])
            found_calendar = next((cal for cal in calendars if cal['summary'].lower() == calendar_name.lower()), None)
            if found_calendar:
                calendar_id = found_calendar['id']
            else:
                return {"error": f"Agenda '{calendar_name}' não encontrada."}

        tz = pytz.timezone(TIMEZONE)
        start_dt = tz.localize(datetime.strptime(f"{preferred_date} {preferred_time}", "%Y-%m-%d %H:%M"))
        end_dt = start_dt + timedelta(hours=float(duration_hours))

        if check_conflicts:
            freebusy_body = {"timeMin": start_dt.isoformat(), "timeMax": end_dt.isoformat(), "timeZone": TIMEZONE, "items": [{"id": calendar_id}]}
            freebusy = service.freebusy().query(body=freebusy_body).execute()
            if freebusy['calendars'][calendar_id]['busy']:
                return {"success": False, "conflict": True, "message": f"Horário {preferred_time} do dia {preferred_date} está ocupado na agenda '{calendar_name or 'principal'}'"}

        event_body = {
            'summary': title, 'description': description,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': TIMEZONE},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': TIMEZONE}
        }
        created_event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        return {"success": True, "event_id": created_event['id'], "title": title, "link": created_event.get('htmlLink')}
    except HttpError as e:
        return {"error": f"An error occurred: {e}"}

# --- FINALIZED TOOL DEFINITIONS ---
tools = [
    {"type": "function", "function": {
        "name": "list_calendars",
        "description": "Lista todas as agendas (calendários) disponíveis para o usuário, com seus nomes e IDs.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "search_events",
        "description": "Busca eventos em uma agenda específica. Use esta ferramenta para obter os IDs de eventos antes de modificá-los ou deletá-los.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": ["string", "null"], "description": "O nome do evento a ser buscado (ex: 'Reunião de marketing')."},
            "calendar_name": {"type": ["string", "null"], "description": "O nome da agenda onde o evento está (ex: 'Trabalho', 'Pessoal'). Se não informado, busca na agenda principal."},
            "date_filter": {"type": ["string", "null"], "description": "Filtra a busca por uma data específica no formato YYYY-MM-DD."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "modify_calendar_event",
        "description": "Modifica ou deleta um evento. Requer o event_id e o calendar_id obtidos através da ferramenta 'search_events'.",
        "parameters": {"type": "object", "properties": {
            "event_id": {"type": "string", "description": "ID do evento obtido de 'search_events'."},
            "calendar_id": {"type": "string", "description": "ID da agenda obtido de 'search_events'."},
            "action": {"type": "string", "enum": ["update", "delete"], "description": "A ação a ser realizada."},
            "new_title": {"type": ["string", "null"], "description": "O novo título para o evento (apenas para 'update')."},
            "new_date": {"type": ["string", "null"], "description": "A nova data no formato YYYY-MM-DD (apenas para 'update')."},
            "new_start_time": {"type": ["string", "null"], "description": "O novo horário no formato HH:MM (apenas para 'update')."},
            "new_duration_hours": {"type": ["number", "null"], "description": "A nova duração em horas (ex: 1.5 para 1h 30min)."}
        }, "required": ["event_id", "calendar_id", "action"]}
    }},
    {"type": "function", "function": {
        "name": "smart_schedule_event",
        "description": "Cria um novo evento, verificando conflitos de horário.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "Título do novo evento."},
            "preferred_date": {"type": "string", "description": "Data do evento no formato YYYY-MM-DD."},
            "preferred_time": {"type": "string", "description": "Horário do evento no formato HH:MM."},
            "calendar_name": {"type": ["string", "null"], "description": "Nome da agenda onde criar o evento (ex: 'Trabalho'). Se não informado, usa a agenda principal."},
            "duration_hours": {"type": ["number", "null"], "description": "Duração em horas (ex: 0.5 para 30 minutos). Padrão: 1."},
            "description": {"type": ["string", "null"], "description": "Descrição ou notas para o evento."}
        }, "required": ["title", "preferred_date", "preferred_time"]}
    }}
]

def get_llm_response(messages, tools, final_call=False):
    tool_choice = "auto" if not final_call else "none"
    model_to_use = "llama-3.1-8b-instant"
    system_prompt = '''
Você é CalendAI, um assistente de agenda amigável e eficiente em português do Brasil (timezone America/Sao_Paulo).

### FLUXO DE TRABALHO OBRIGATÓRIO
1.  **PARA LISTAR AGENDAS:** Use `list_calendars`.
2.  **PARA MODIFICAR/DELETAR:** Use `search_events` PRIMEIRO para obter `event_id` e `calendar_id`.
3.  **AÇÃO FINAL:** Use os IDs obtidos para chamar `modify_calendar_event` ou `smart_schedule_event`.
4.  **REGRAS DE CHAMADA:** Para `modify_calendar_event` com `action="delete"`, NÃO envie parâmetros `new_*`.

### MANUAL DE ESTILO PARA RESPOSTAS (Use Markdown)
-   **Confirmações de Ações:**
    -   **Criação:** Comece com "✅ **Evento Criado!**\n". Em seguida, mostre os detalhes e o link.
    -   **Atualização:** Comece com "🔄 **Evento Atualizado!**\n". Em seguida, mostre os detalhes e o link.
    -   **Deleção:** Comece com "🗑️ **Evento Deletado!**\n". Confirme qual evento foi removido.
-   **Listagem de Agendas:**
    -   Use o título: "### 🗓️ Suas Agendas\n"
    -   Liste cada agenda com um hífen. Ex: `- Pessoal`
-   **Listagem de Eventos Encontrados:**
    -   Use o título: "### 🔍 Eventos Encontrados\n"
    -   Liste cada evento com detalhes (data/hora).
-   **Nenhum Evento Encontrado:**
    -   Use: "ℹ️ Nenhum evento encontrado com os critérios fornecidos."
-   **Conflito de Horário:**
    -   Use: "⚠️ **Conflito de Horário!** O horário solicitado já está ocupado. Por favor, escolha outro."
-   **Erros Gerais:**
    -   Use: "Desculpe, não consegui processar sua solicitação. A ferramenta retornou um erro."
-   **SEMPRE** use formatação clara e agradável. **NUNCA** mostre IDs para o usuário, apenas os nomes e detalhes relevantes.
'''
    messages_with_system_prompt = [{"role": "system", "content": system_prompt}] + messages
    try:
        response = groq_client.chat.completions.create(model=model_to_use, messages=messages_with_system_prompt, tools=tools, tool_choice=tool_choice, temperature=0, stream=False)
        return response
    except Exception as e:
        print(f"Groq failed, falling back to OpenAI: {e}")
        # Fallback implementation...
        return None

def sanitize_message_for_api(message):
    if hasattr(message, 'model_dump'):
        clean_message = message.model_dump(exclude_unset=True, exclude={'annotations', 'refusal'})
        if clean_message.get('content') is None and not clean_message.get('tool_calls'):
            clean_message['content'] = ""
        return clean_message
    return message

# --- OAuth & App Routes ---
CLIENT_SECRETS_FILE = 'client_secret.json'
SCOPES = ['https://www.googleapis.com/auth/calendar']
REDIRECT_URI = 'https://5000-firebase-mcp-automation-1765672594756.cluster-fsmcisrvfbb5cr5mvra3hr3qyg.cloudworkstations.dev/oauth2callback'

@app.route('/')
def index():
    return render_template('index.html', auth_url=url_for('authorize'), theme=session.get('theme', 'dark'))

@app.route('/authorize')
def authorize():
    cache = load_cache()
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='consent')
    cache[state] = {'flow': True}
    save_cache(cache)
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    cache = load_cache()
    state = request.args.get('state')
    if not state or not cache.get(state, {}).get('flow'):
        return render_template('error.html', message="Requisição inválida."), 400
    if state in cache: del cache[state]
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI)
    flow.fetch_token(authorization_response=request.url.replace('http://', 'https://', 1))
    credentials = flow.credentials
    cred_token = secrets.token_urlsafe(32)
    cache[cred_token] = {'token': credentials.token, 'refresh_token': credentials.refresh_token, 'token_uri': credentials.token_uri, 'client_id': credentials.client_id, 'client_secret': credentials.client_secret, 'scopes': credentials.scopes}
    save_cache(cache)
    return redirect(url_for('chat', token=cred_token))

def get_credentials_from_token(token):
    cache = load_cache()
    return cache.get(token)

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    token = request.args.get('token')
    if not token: return redirect(url_for('authorize'))
    credentials_info = get_credentials_from_token(token)
    if not credentials_info: return render_template('error.html', message="Sessão expirada."), 401

    if request.method == 'POST':
        messages = request.json.get('messages', [])
        try:
            service = get_calendar_service(credentials_info)
            available_functions = {
                "list_calendars": lambda **args: list_calendars(service, **args),
                "search_events": lambda **args: search_events(service, **args),
                "modify_calendar_event": lambda **args: modify_calendar_event(service, **args),
                "smart_schedule_event": lambda **args: smart_schedule_event(service, **args)
            }
            
            response = get_llm_response(messages=messages, tools=tools)
            if not response: # Handle fallback failure
                return jsonify({"reply": "Desculpe, o serviço de IA está indisponível no momento."}), 503

            response_message = response.choices[0].message
            messages.append(sanitize_message_for_api(response_message))

            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_to_call = available_functions.get(function_name)
                    if function_to_call:
                        function_args = json.loads(tool_call.function.arguments) or {}
                        function_response = function_to_call(**function_args)
                        messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": json.dumps(function_response, default=str)})
                    else:
                        error_content = json.dumps({"error": f"Tool '{function_name}' não existe."})
                        messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": error_content})
                
                second_response = get_llm_response(messages=messages, tools=tools, final_call=True)
                if not second_response: # Handle fallback failure
                    return jsonify({"reply": "Desculpe, o serviço de IA está indisponível no momento."}), 503
                
                second_response_message = second_response.choices[0].message
                messages.append(sanitize_message_for_api(second_response_message))
                return jsonify({"reply": second_response_message.content, "messages": messages})
            else:
                return jsonify({"reply": response_message.content, "messages": messages})

        except Exception as e:
            print(f"An unexpected error occurred in /chat: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"reply": "Desculpe, ocorreu um erro inesperado e grave no servidor."}), 500

    return render_template('chat.html', token=token, theme=session.get('theme', 'dark'))


@app.route('/set-theme', methods=['POST'])
def set_theme():
    session['theme'] = request.json.get('theme')
    return jsonify(success=True)

@app.context_processor
def inject_now():
    return {'anocorrente': datetime.utcnow().year}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
