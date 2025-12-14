
import os
import json
import secrets
from datetime import datetime, timedelta, timezone
import dateutil.parser
import dateutil.tz
import requests  # Importa a biblioteca requests
from flask import Flask, redirect, url_for, request, render_template
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-segura-e-dificil-de-adivinhar'

# --- IMPLEMENTAÇÃO DE CACHE PERSISTENTE --- #
STATE_CACHE_FILE = '/tmp/oauth_state_cache.json'

def load_cache():
    """Carrega o cache de um arquivo JSON."""
    if not os.path.exists(STATE_CACHE_FILE):
        return {}
    try:
        with open(STATE_CACHE_FILE, 'r') as f:
            raw_cache = json.load(f)
            for key, value in raw_cache.items():
                if 'created_at' in value:
                    raw_cache[key]['created_at'] = datetime.fromisoformat(value['created_at'])
            return raw_cache
    except (IOError, json.JSONDecodeError):
        return {}

def save_cache(cache):
    """Salva o cache em um arquivo JSON."""
    serializable_cache = {}
    for key, value in cache.items():
        serializable_cache[key] = value.copy()
        if 'created_at' in serializable_cache[key] and isinstance(serializable_cache[key]['created_at'], datetime):
            serializable_cache[key]['created_at'] = serializable_cache[key]['created_at'].isoformat()
    
    with open(STATE_CACHE_FILE, 'w') as f:
        json.dump(serializable_cache, f, indent=2)

def get_utc_now():
    return datetime.now(timezone.utc)

def clean_old_entries(cache):
    """Remove entradas do cache com mais de 10 minutos."""
    now = get_utc_now()
    expired_keys = [k for k, v in cache.items() if now - v.get('created_at', now) > timedelta(minutes=10)]
    for k in expired_keys:
        if k in cache: del cache[k]
    return cache
# --- FIM DA IMPLEMENTAÇÃO DE CACHE --- #

CLIENT_SECRETS_FILE = 'client_secret.json'
SCOPES = ['https://www.googleapis.com/auth/calendar']
REDIRECT_URI = 'https://5000-firebase-mcp-automation-1765672594756.cluster-fsmcisrvfbb5cr5mvra3hr3qyg.cloudworkstations.dev/oauth2callback'
CALENDAR_TO_ADD_ID = 'c_312e33b3e0912443d3f966c8bf080479f9725f3817a1c1d0411a052df3c483d4@group.calendar.google.com'

def send_whatsapp_notification(summary, start_time, end_time):
    """Envia uma notificação para a Cloud Function que chama o WhatsApp."""
    cloud_function_url = os.environ.get("WHATSAPP_CLOUD_FUNCTION_URL")
    to_whatsapp_number = os.environ.get("TO_WHATSAPP_NUMBER")

    if not cloud_function_url or not to_whatsapp_number:
        print("URL da Cloud Function ou número do WhatsApp não configurados.")
        return

    if 'sua_url_da_cloud_function' in cloud_function_url:
        print("URL da Cloud Function ainda não foi configurada no arquivo .env.")
        return

    message_body = f"Novo evento na agenda: *{summary}*\n\n*Início:* {start_time}\n*Fim:* {end_time}"
    
    payload = {
        'to': to_whatsapp_number,
        'message': message_body
    }

    try:
        response = requests.post(cloud_function_url, json=payload, timeout=10)
        response.raise_for_status()  # Lança uma exceção para respostas com erro (4xx ou 5xx)
        print(f"Notificação enviada com sucesso para a Cloud Function. Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar notificação para a Cloud Function: {e}")


@app.route('/')
def index():
    auth_url = url_for('authorize')
    return render_template('index.html', auth_url=auth_url)

@app.route('/authorize')
def authorize():
    cache = load_cache()
    cache = clean_old_entries(cache)
    
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='consent')

    cache[state] = {'created_at': get_utc_now(), 'used': False}
    save_cache(cache)
    
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    cache = load_cache()
    state = request.args.get('state')
    
    if not state or state not in cache or cache[state].get('used'):
        return render_template('error.html', message="State inválido, expirado ou já utilizado."), 400
    
    cache[state]['used'] = True
    
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI)
    auth_response_url = request.url.replace('http://', 'https://', 1)
    flow.fetch_token(authorization_response=auth_response_url)

    credentials = flow.credentials
    cred_token = secrets.token_urlsafe(32)
    cache[cred_token] = {
        'credentials': {
            'token': credentials.token, 'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri, 'client_id': credentials.client_id,
            'client_secret': credentials.client_secret, 'scopes': credentials.scopes
        },
        'created_at': get_utc_now()
    }
    
    if state in cache: del cache[state]
    save_cache(cache)
    return redirect(url_for('list_calendars', token=cred_token))

def get_credentials_from_token(token):
    cache = load_cache()
    if not token or token not in cache:
        return None
    return Credentials(**cache[token]['credentials'])

@app.route('/calendars')
def list_calendars():
    cred_token = request.args.get('token')
    credentials = get_credentials_from_token(cred_token)
    if not credentials:
        return redirect(url_for('authorize'))
    
    try:
        service = build('calendar', 'v3', credentials=credentials)
        
        calendars_result = service.calendarList().list().execute()
        calendars_data = calendars_result.get('items', [])
        
        calendar_ids = {item['id'] for item in calendars_data}
        if CALENDAR_TO_ADD_ID not in calendar_ids:
            try:
                calendar_to_add = service.calendars().get(calendarId=CALENDAR_TO_ADD_ID).execute()
                calendars_data.append(calendar_to_add)
            except HttpError as error:
                print(f"Não foi possível encontrar a agenda com o ID {CALENDAR_TO_ADD_ID}: {error}")

        all_calendar_ids = [item['id'] for item in calendars_data]
        now_utc = datetime.now(timezone.utc)
        start_of_day_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day_utc = start_of_day_utc + timedelta(days=1, microseconds=-1)

        freebusy_query = {
            'timeMin': start_of_day_utc.isoformat(),
            'timeMax': end_of_day_utc.isoformat(),
            'items': [{'id': cal_id} for cal_id in all_calendar_ids]
        }
        freebusy_result = service.freebusy().query(body=freebusy_query).execute()

        calendars = []
        for calendar_item in calendars_data:
            calendar_id = calendar_item['id']
            tz_str = calendar_item.get('timeZone', 'UTC')
            tz = dateutil.tz.gettz(tz_str)
            now_in_tz = datetime.now(tz)

            busy_intervals = freebusy_result.get('calendars', {}).get(calendar_id, {}).get('busy', [])
            next_available_slot = "Nenhum horário hoje"
            
            day_start = now_in_tz.replace(hour=9, minute=0, second=0, microsecond=0)
            day_end = now_in_tz.replace(hour=18, minute=0, second=0, microsecond=0)
            
            slot_time = max(day_start, now_in_tz)

            while slot_time < day_end:
                slot_end_time = slot_time + timedelta(hours=1)
                is_busy = False
                for busy in busy_intervals:
                    busy_start = dateutil.parser.isoparse(busy['start'])
                    busy_end = dateutil.parser.isoparse(busy['end'])
                    if max(slot_time, busy_start) < min(slot_end_time, busy_end):
                        is_busy = True
                        break
                
                if not is_busy and slot_time.hour < 18:
                    next_available_slot = f"Disponível às {slot_time.strftime('%H:%M')}"
                    break

                slot_time += timedelta(minutes=15)

            calendars.append({
                'summary': calendar_item['summary'],
                'events_url': url_for('list_events', calendar_id=calendar_id, token=cred_token),
                'availability': next_available_slot
            })
        
        return render_template('calendars.html', calendars=calendars)

    except HttpError as error:
        print(f"Ocorreu um erro ao buscar a lista de calendários: {error}")
        return render_template('error.html', message=f"Ocorreu um erro ao buscar a lista de calendários: {error}"), 500

@app.route('/events/<calendar_id>')
def list_events(calendar_id):
    cred_token = request.args.get('token')
    credentials = get_credentials_from_token(cred_token)
    if not credentials:
        return redirect(url_for('authorize'))

    try:
        service = build('calendar', 'v3', credentials=credentials)
        
        calendar_resource = service.calendars().get(calendarId=calendar_id).execute()
        calendar_timezone = calendar_resource['timeZone']
        tz = dateutil.tz.gettz(calendar_timezone)
        now_in_tz = datetime.now(tz)

        events_result = service.events().list(
            calendarId=calendar_id, timeMin=now_in_tz.isoformat(),
            maxResults=10, singleEvents=True, orderBy='startTime').execute()
        events_data = events_result.get('items', [])
        
        events = []
        for item in events_data:
            start_str = item['start'].get('dateTime', item['start'].get('date'))
            
            formatted_start = ""
            try:
                if 'T' in start_str: # É um datetime com fuso horário
                    dt_object = dateutil.parser.isoparse(start_str)
                    formatted_start = dt_object.strftime('%d/%m/%Y %H:%M')
                else: # É apenas uma data (evento de dia inteiro)
                    dt_object = datetime.strptime(start_str, '%Y-%m-%d').date()
                    formatted_start = dt_object.strftime('%d/%m/%Y')
            except ValueError:
                formatted_start = start_str # Ffallback para a string original

            events.append({'id': item['id'], 'summary': item['summary'], 'start': formatted_start})

        start_of_day = now_in_tz.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1, microseconds=-1)
        
        freebusy_query = {
            'timeMin': start_of_day.isoformat(),
            'timeMax': end_of_day.isoformat(),
            'timeZone': calendar_timezone,
            'items': [{'id': calendar_id}]
        }
        freebusy_result = service.freebusy().query(body=freebusy_query).execute()
        busy_intervals = freebusy_result['calendars'][calendar_id]['busy']
        
        availability_slots = []
        day_start_hour = 9
        day_end_hour = 18
        slot_time = start_of_day.replace(hour=day_start_hour, minute=0)

        while slot_time.hour < day_end_hour:
            slot_end_time = slot_time + timedelta(hours=1)
            is_busy = False
            for busy in busy_intervals:
                busy_start = dateutil.parser.isoparse(busy['start'])
                busy_end = dateutil.parser.isoparse(busy['end'])
                if max(slot_time, busy_start) < min(slot_end_time, busy_end):
                    is_busy = True
                    break
            
            availability_slots.append({
                'time': slot_time.strftime('%H:%M'),
                'status': 'Ocupado' if is_busy else 'Disponível'
            })
            slot_time = slot_end_time

        back_url = url_for('list_calendars', token=cred_token)
        create_event_url = url_for('create_event', calendar_id=calendar_id, token=cred_token)
        return render_template('events.html', 
                               events=events, 
                               availability_slots=availability_slots,
                               back_url=back_url, 
                               create_event_url=create_event_url, 
                               calendar_id=calendar_id, 
                               token=cred_token)

    except (HttpError, KeyError) as error:
        print(f"Ocorreu um erro: {error}")
        return render_template('error.html', message=f"Ocorreu um erro ao buscar detalhes do calendário: {error}"), 500

@app.route('/create_event/<calendar_id>', methods=['GET', 'POST'])
def create_event(calendar_id):
    cred_token = request.args.get('token')
    credentials = get_credentials_from_token(cred_token)
    if not credentials:
        return redirect(url_for('authorize'))

    service = build('calendar', 'v3', credentials=credentials)
    back_url = url_for('list_events', calendar_id=calendar_id, token=cred_token)

    if request.method == 'POST':
        try:
            summary = request.form['summary']
            start_datetime_str = request.form['start_datetime']
            end_datetime_str = request.form['end_datetime']
            
            time_min = datetime.fromisoformat(start_datetime_str).isoformat() + 'Z'
            time_max = datetime.fromisoformat(end_datetime_str).isoformat() + 'Z'

            freebusy_query = {
                'timeMin': time_min,
                'timeMax': time_max,
                'items': [{'id': calendar_id}]
            }
            freebusy_result = service.freebusy().query(body=freebusy_query).execute()
            busy_intervals = freebusy_result.get('calendars', {}).get(calendar_id, {}).get('busy', [])

            if busy_intervals:
                error_message = "O horário selecionado já está ocupado. Por favor, escolha outro."
                return render_template('create_event.html', 
                                       back_url=back_url,
                                       error_message=error_message)

            calendar_resource = service.calendars().get(calendarId=calendar_id).execute()
            calendar_timezone = calendar_resource['timeZone']

            event_body = {
                'summary': summary,
                'start': {'dateTime': datetime.fromisoformat(start_datetime_str).isoformat(), 'timeZone': calendar_timezone},
                'end': {'dateTime': datetime.fromisoformat(end_datetime_str).isoformat(), 'timeZone': calendar_timezone},
                'transparency': 'opaque',
            }

            service.events().insert(calendarId=calendar_id, body=event_body).execute()
            
            # Enviar notificação para a Cloud Function
            send_whatsapp_notification(summary, start_datetime_str, end_datetime_str)
            
            return redirect(url_for('list_events', calendar_id=calendar_id, token=cred_token))

        except HttpError as error:
            print(f'Ocorreu um erro: {error}')
            return render_template('error.html', message=f"Ocorreu um erro ao criar o evento: {error}"), 500

    return render_template('create_event.html', back_url=back_url)


@app.route('/delete_event/<calendar_id>/<event_id>', methods=['POST'])
def delete_event(calendar_id, event_id):
    cred_token = request.args.get('token')
    credentials = get_credentials_from_token(cred_token)
    if not credentials:
        return redirect(url_for('authorize'))

    try:
        service = build('calendar', 'v3', credentials=credentials)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except HttpError as error:
        print(f'Ocorreu um erro ao excluir o evento: {error}')
        return render_template('error.html', message=f"Ocorreu um erro ao excluir o evento: {error}"), 500

    return redirect(url_for('list_events', calendar_id=calendar_id, token=cred_token))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
