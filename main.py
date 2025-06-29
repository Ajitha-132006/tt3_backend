import os
import json
from fastapi import FastAPI, Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
import pytz
import re

from langchain_community.llms import HuggingFaceHub

# --- GOOGLE CALENDAR SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Load service account from env variable
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
credentials = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)
calendar_service = build('calendar', 'v3', credentials=credentials)
calendar_id = 'primary'

# --- FASTAPI SETUP ---
app = FastAPI()

# --- LLM SETUP ---
llm = HuggingFaceHubChat(
    repo_id="HuggingFaceH4/zephyr-7b-beta",
    huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

# --- HELPER FUNCTIONS ---
def search_slots(start_time, end_time):
    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=start_time.isoformat(),
        timeMax=end_time.isoformat(),
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
    if "tomorrow" in text:
        start = datetime.utcnow() + timedelta(days=1, hours=15)
    elif "next week" in text:
        start = datetime.utcnow() + timedelta(days=7, hours=15)
    elif "friday" in text:
        today = datetime.utcnow()
        days_ahead = (4 - today.weekday()) % 7
        days_ahead = 7 if days_ahead == 0 else days_ahead
        start = today + timedelta(days=days_ahead, hours=15)
    else:
        start = datetime.utcnow() + timedelta(days=1, hours=15)
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
        return "Can you please specify a date or time for the appointment?"

# --- FASTAPI ROUTE ---
@app.post("/chat")
async def chat_api(req: Request):
    data = await req.json()
    user_message = data.get("message", "")
    response = handle_chat(user_message)
    return {"reply": response}
