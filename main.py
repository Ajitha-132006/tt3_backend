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
    tomorrow = datetime.utcnow() + timedelta(days=1)
    suggested = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 15, 0, 0, tzinfo=pytz.UTC)
    return suggested.isoformat()

def create_event(start_time, end_time, summary="Meeting"):
    event = {
        'summary': summary,
        'start': {'dateTime': start_time, 'timeZone': 'UTC'},
        'end': {'dateTime': end_time, 'timeZone': 'UTC'}
    }
    created_event = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    return created_event.get('htmlLink')

def parse_time_input(text):
    now = datetime.utcnow()
    
    if "tomorrow" in text:
        target_date = now + timedelta(days=1)
        start = datetime(target_date.year, target_date.month, target_date.day, 15, 0, 0, tzinfo=pytz.UTC)
    elif "next week" in text:
        target_date = now + timedelta(days=7)
        start = datetime(target_date.year, target_date.month, target_date.day, 15, 0, 0, tzinfo=pytz.UTC)
    elif "friday" in text:
        days_ahead = (4 - now.weekday()) % 7
        days_ahead = 7 if days_ahead == 0 else days_ahead
        target_date = now + timedelta(days=days_ahead)
        start = datetime(target_date.year, target_date.month, target_date.day, 15, 0, 0, tzinfo=pytz.UTC)
    else:
        # Default: tomorrow at 3 PM UTC
        target_date = now + timedelta(days=1)
        start = datetime(target_date.year, target_date.month, target_date.day, 15, 0, 0, tzinfo=pytz.UTC)
    
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
            return f"Meeting booked! Here’s the link: {link}"
    elif re.search(r'free|available|slot', user_input, re.I):
        suggestion = suggest_slot()
        return f"You're free at {suggestion}. Shall I book it?"
    else:
        # Let LLM handle vague inputs
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
