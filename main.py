
import os
import json
import secrets
from datetime import datetime, timezone, timedelta
from flask import Flask, redirect, url_for, request, render_template, jsonify, session
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

# --- OpenAI Configuration ---
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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

# --- Google Calendar API Functions ---
def get_calendar_service(credentials_info):
    credentials = Credentials(**credentials_info)
    return build('calendar', 'v3', credentials=credentials)

def list_calendars(service):
    try:
        calendar_list = service.calendarList().list().execute()
        return calendar_list.get('items', [])
    except HttpError as error:
        return {"error": f"An error occurred: {error}"}

def list_events(service, calendar_id='primary', query=None, relative_date=None, start_date=None, end_date=None, duration_days=None, max_results=10):
    try:
        now = datetime.now(timezone.utc)
        time_min, time_max = None, None

        if relative_date == 'hoje':
            time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = time_min + timedelta(days=1) - timedelta(seconds=1)
        elif relative_date == 'amanha':
            time_min = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = time_min + timedelta(days=1) - timedelta(seconds=1)
        elif start_date:
            time_min = datetime.fromisoformat(start_date.split('T')[0] + 'T00:00:00+00:00')
            time_max = (time_min + timedelta(days=duration_days)) if duration_days else (datetime.fromisoformat(end_date.split('T')[0] + 'T23:59:59+00:00') if end_date else (time_min + timedelta(days=1) - timedelta(seconds=1)))
        elif query is None:
            time_min = now
            time_max = now + timedelta(days=duration_days if duration_days else 7)

        events_result = service.events().list(
            calendarId=calendar_id, 
            timeMin=time_min.isoformat() if time_min else None,
            timeMax=time_max.isoformat() if time_max else None,
            q=query,
            maxResults=max_results, 
            singleEvents=True, 
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        if not events:
            return [{"message": "Nenhum evento encontrado com esses critérios."}]
            
        simplified_events = []
        for event in events:
            simplified_events.append({
                'id': event['id'], # <-- ID do evento adicionado
                'summary': event.get('summary', 'Sem Título'),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date'))
            })
        return simplified_events
    except HttpError as error:
        return {"error": f"An error occurred: {error}"}

def create_event(service, summary, start_time, end_time, calendar_id='primary', description=None, location=None, attendees=None):
    try:
        event_body = {
            'summary': summary, 'start': {'dateTime': start_time, 'timeZone': 'UTC'},
            'end': {'dateTime': end_time, 'timeZone': 'UTC'},
        }
        if description: event_body['description'] = description
        if location: event_body['location'] = location
        if attendees: event_body['attendees'] = [{'email': email} for email in attendees]
        
        created_event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        return {"status": "Evento criado com sucesso!", "summary": created_event.get('summary')}
    except HttpError as error:
        return {"error": f"An error occurred: {error}"}

# --- NOVA FUNÇÃO DE EXCLUSÃO ---
def delete_event(service, event_id, calendar_id='primary'):
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"status": "Evento excluído com sucesso!"}
    except HttpError as error:
        if error.resp.status == 404:
            return {"error": "Evento não encontrado. Ele pode já ter sido excluído."}
        return {"error": f"Ocorreu um erro ao excluir o evento: {error}"}

# --- Definições de Ferramentas Otimizadas para a OpenAI ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "list_calendars",
            "description": "Lista todas as agendas de calendário disponíveis."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "Busca e lista eventos. Retorna uma lista de eventos, incluindo o ID de cada um, necessário para exclusões.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_id": {"type": "string", "description": "ID da agenda. Padrão: 'primary'"},
                    "query": {"type": "string", "description": "Texto para pesquisar no título dos eventos. Use para encontrar um evento específico antes de excluir."},
                    "relative_date": {"type": "string", "enum": ["hoje", "amanha"], "description": "Busca por datas relativas como 'hoje' ou 'amanhã'."},
                    "duration_days": {"type": "integer", "description": "Duração em dias a partir de agora, ex: 7 para 'próxima semana'."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Cria um novo evento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "O título do evento."},
                    "start_time": {"type": "string", "description": "Início do evento (ISO 8601)."},
                    "end_time": {"type": "string", "description": "Término do evento (ISO 8601)."}
                },
                "required": ["summary", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Exclui um evento usando seu ID. Você DEVE primeiro usar list_events com o nome do evento para encontrar o ID correto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "O ID do evento a ser excluído."},
                    "calendar_id": {"type": "string", "description": "O ID da agenda. Padrão: 'primary'."}
                },
                "required": ["event_id"]
            }
        }
    }
]

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
    cache[cred_token] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
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
                "list_calendars": lambda: list_calendars(service),
                "list_events": lambda **args: list_events(service, **args),
                "create_event": lambda **args: create_event(service, **args),
                "delete_event": lambda **args: delete_event(service, **args)
            }
            
            response = client.chat.completions.create(model="gpt-4-turbo-preview", messages=messages, tools=tools, tool_choice="auto")
            response_message = response.choices[0].message
            messages.append(response_message.model_dump(exclude_unset=True))

            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_to_call = available_functions.get(function_name)
                    function_args = json.loads(tool_call.function.arguments)
                    function_response = function_to_call(**function_args)
                    messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": json.dumps(function_response, default=str)})
                
                second_response = client.chat.completions.create(model="gpt-4-turbo-preview", messages=messages)
                second_response_message = second_response.choices[0].message
                messages.append(second_response_message.model_dump(exclude_unset=True))
                return jsonify({"reply": second_response_message.content, "messages": messages})
            else:
                return jsonify({"reply": response_message.content, "messages": messages})

        except Exception as e:
            print(f"An unexpected error occurred in /chat: {e}")
            return jsonify({"reply": "Desculpe, ocorreu um erro inesperado no servidor."}), 500

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
