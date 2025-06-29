import os
import json
import re
from datetime import datetime, timedelta
import pytz

from fastapi import FastAPI, Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
import dateparser
from langchain_community.llms import HuggingFaceHub

# --- GOOGLE CALENDAR SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
credentials = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)
calendar_service = build('calendar', 'v3', credentials=credentials)
calendar_id = 'chalasaniajitha@gmail.com'

# --- LLM SETUP ---
llm = HuggingFaceHub(
    repo_id="HuggingFaceH4/zephyr-7b-beta",
    huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

# --- FASTAPI APP ---
app = FastAPI()

# --- HELPER FUNCTIONS ---
def search_slots(start_time, end_time):
    time_min = start_time.isoformat()
    time_max = end_time.isoformat()
    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    return events_result.get('items', [])

def suggest_slot():
    tomorrow = datetime.utcnow() + timedelta(days=1)
    suggested = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, 15, 0, 0, tzinfo=pytz.UTC
    )
    return suggested.isoformat()

def create_event(start_time, end_time, summary="Meeting"):
    event = {
        'summary': summary,
        'start': {'dateTime': start_time, 'timeZone': 'UTC'},
        'end': {'dateTime': end_time, 'timeZone': 'UTC'}
    }
    created_event = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    return created_event.get('htmlLink')

def llm_extract_event_info(user_input):
    system_prompt = (
        "Extract the intent, event title, and datetime phrase from the user input. "
        "Return JSON: {\"intent\": \"book_event/check_availability/other\", \"title\": \"...\", \"datetime_phrase\": \"...\"}. "
        "If not clear, use sensible defaults."
    )
    combined_input = f"{system_prompt}\nUser: {user_input}"
    reply = llm.invoke(combined_input)
    try:
        info = json.loads(reply)
        return info
    except json.JSONDecodeError:
        raise ValueError(f"LLM returned invalid JSON: {reply}")

def parse_time_input(text):
    dt = dateparser.parse(
        text,
        settings={'RETURN_AS_TIMEZONE_AWARE': True, 'TIMEZONE': 'UTC'}
    )
    if not dt:
        raise ValueError(f"Couldn't parse time from: {text}")
    start = dt
    end = start + timedelta(hours=1)
    return start, end

def handle_chat(user_input):
    info = llm_extract_event_info(user_input)
    intent = info.get("intent")
    title = info.get("title", "Meeting")
    datetime_phrase = info.get("datetime_phrase")

    if intent == "book_event":
        start, end = parse_time_input(datetime_phrase)
        existing = search_slots(start, end)
        if existing:
            suggestion = suggest_slot()
            return f"You're busy at that time. How about {suggestion}?"
        else:
            link = create_event(start.isoformat(), end.isoformat(), summary=title)
            # Format clean short link
            return f"{title.capitalize()} booked! [View here]({link})"
    
    elif intent == "check_availability":
        suggestion = suggest_slot()
        return f"You're free at {suggestion}. Shall I book it?"
    
    else:
        return llm.invoke(user_input)

# --- API ROUTES ---
@app.post("/")
async def chat_api(req: Request):
    data = await req.json()
    user_message = data.get("message", "")
    response = handle_chat(user_message)
    return {"reply": response}

@app.get("/")
async def root():
    return {"message": "Smart Calendar Bot is running!"}
