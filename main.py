import os
import json
import re
from datetime import datetime, timedelta

import pytz
import requests
from fastapi import FastAPI, Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
from dateparser.search import search_dates

# --- GOOGLE CALENDAR SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar']

SERVICE_ACCOUNT_INFO = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
credentials = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)
calendar_service = build('calendar', 'v3', credentials=credentials)
calendar_id = 'chalasaniajitha@gmail.com'

# --- HUGGING FACE CONFIG ---
HF_TOKEN = os.getenv("HUGGINGFACEHUB_API_TOKEN")
HF_REPO = "HuggingFaceH4/zephyr-7b-beta"  # Or change to another model

# --- FASTAPI APP ---
app = FastAPI()

# --- HELPER FUNCTIONS ---
def detect_event_type(user_input):
    prompt = f"Identify the event type (e.g., Meeting, Call, Lunch, Flight) from this text: {user_input}\nEvent type:"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}"
    }
    json_data = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 10}
    }
    response = requests.post(
        f"https://api-inference.huggingface.co/models/{HF_REPO}",
        headers=headers,
        json=json_data
    )
    if response.status_code == 200:
        generated = response.json()[0]["generated_text"]
        event_type = generated.split("Event type:")[-1].strip()
        return event_type if event_type else "Event"
    else:
        return "Event"

def parse_time_input(user_input):
    result = search_dates(
        user_input,
        settings={
            'PREFER_DATES_FROM': 'future',
            'RETURN_AS_TIMEZONE_AWARE': True,
            'TIMEZONE': 'Asia/Kolkata',
            'RELATIVE_BASE': datetime.now(pytz.timezone('Asia/Kolkata'))
        }
    )
    if result:
        dt = result[0][1]
        if dt.tzinfo is None:
            dt = pytz.timezone('Asia/Kolkata').localize(dt)
        return dt
    else:
        return None

def check_availability(start, end):
    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    return len(events) == 0

def create_event(summary, start, end):
    event = {
        'summary': summary,
        'start': {'dateTime': start.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end.isoformat(), 'timeZone': 'Asia/Kolkata'}
    }
    created = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    return created.get('htmlLink')

# --- MAIN CHAT HANDLER ---
def handle_chat(user_input):
    start = parse_time_input(user_input)
    if not start:
        return "⚠ I couldn’t understand the date/time. Try saying something like 'tomorrow at 4 PM' or 'next Friday 10 AM'."

    end = start + timedelta(minutes=30)
    event_type = detect_event_type(user_input)

    if check_availability(start, end):
        link = create_event(event_type, start, end)
        return f"✅ Booked {event_type} for {start.strftime('%Y-%m-%d %I:%M %p')}. [View in Calendar]({link})"
    else:
        # Suggest next available slot
        for i in range(1, 4):
            alt_start = start + timedelta(hours=i)
            alt_end = alt_start + timedelta(minutes=30)
            if check_availability(alt_start, alt_end):
                return f"❌ You're busy at requested time. How about {alt_start.strftime('%Y-%m-%d %I:%M %p')}?"
        return "❌ You're busy at the requested time and no nearby slots were found. Please suggest another time."

# --- API ROUTES ---
@app.post("/")
async def chat_api(req: Request):
    data = await req.json()
    user_message = data.get("message", "")
    reply = handle_chat(user_message)
    return {"reply": reply}

@app.get("/")
async def root():
    return {"message": "HuggingFace + Google Calendar bot is running!"}
