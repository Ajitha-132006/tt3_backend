import os
import json
import re
from datetime import datetime, timedelta

import pytz
from fastapi import FastAPI, Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
from langchain_community.llms import HuggingFaceHub

# --- GOOGLE CALENDAR SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Load service account from environment variable
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
    time_min = start_time.replace(microsecond=0).isoformat() + "Z"
    time_max = end_time.replace(microsecond=0).isoformat() + "Z"
    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    return events_result.get('items', [])

def suggest_slot():
    tomorrow = datetime.utcnow().date() + timedelta(days=1)
    suggested = datetime.combine(tomorrow, datetime.min.time()).replace(
        hour=15, minute=0, second=0, tzinfo=pytz.UTC
    )
    return suggested.isoformat()

def create_event(start_time, end_time, summary="Meeting"):
    event = {
        'summary': summary,
        'start': {'dateTime': start_time, 'timeZone': 'UTC'},
        'end': {'dateTime': end_time, 'timeZone': 'UTC'}
    }
    created_event = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    link = created_event.get('htmlLink')
    return f"<a href='{link}' target='_blank'>View here</a>"

def parse_time_input(text):
    now = datetime.utcnow()
    text_lower = text.lower()

    if "tomorrow" in text_lower:
        target_date = now.date() + timedelta(days=1)
    elif "next week" in text_lower:
        target_date = now.date() + timedelta(days=7)
    elif "friday" in text_lower:
        days_ahead = (4 - now.weekday() + 7) % 7
        days_ahead = days_ahead if days_ahead != 0 else 7
        target_date = now.date() + timedelta(days=days_ahead)
    else:
        target_date = now.date() + timedelta(days=1)

    start = datetime.combine(target_date, datetime.min.time()).replace(
        hour=15, minute=0, second=0, tzinfo=pytz.UTC
    )
    end = start + timedelta(hours=1)
    return start, end

def handle_chat(user_input):
    if re.search(r'book|schedule|meeting|appointment', user_input, re.I):
        start, end = parse_time_input(user_input)
        existing = search_slots(start, end)
        if existing:
            suggestion = suggest_slot()
            return f"You're busy then. How about {suggestion}?"
        else:
            link = create_event(start.isoformat(), end.isoformat())
            return f"Meeting booked! {link}"
    elif re.search(r'free|available|slot', user_input, re.I):
        suggestion = suggest_slot()
        return f"You're free at {suggestion}. Shall I book it?"
    else:
        llm_reply = llm.invoke(user_input)
        return llm_reply

# --- API ROUTES ---
@app.post("/")
async def chat_api(req: Request):
    data = await req.json()
    user_message = data.get("message", "")
    response = handle_chat(user_message)
    return {"reply": response}

@app.get("/")
async def root():
    return {"message": "HuggingFace + Google Calendar bot is running!"}
