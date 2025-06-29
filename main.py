import os
import json
import re
from datetime import datetime, timedelta

import pytz
from fastapi import FastAPI, Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
from langchain_community.llms import HuggingFaceHub
from dateparser.search import search_dates

# --- GOOGLE CALENDAR SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
credentials = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)
calendar_id = 'chalasaniajitha@gmail.com'

# --- LLM SETUP ---
llm = HuggingFaceHub(
    repo_id="HuggingFaceH4/zephyr-7b-beta",
    huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

# --- FASTAPI APP ---
app = FastAPI()

# --- HELPERS ---
def check_availability(start_time, end_time):
    time_min = start_time.isoformat()
    time_max = end_time.isoformat()
    events = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])
    return len(events) == 0

def create_event(summary, start_time, end_time):
    event = {
        'summary': summary,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'}
    }
    created = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    return created.get('htmlLink')

def detect_event_type(user_input):
    prompt = (
        f"From this request: '{user_input}', what should be the title of the calendar event? "
        f"Return a short phrase like 'Team Meeting', 'Lunch with Raj', etc. If unclear, return 'General Event'."
    )
    title = llm.invoke(prompt).strip()
    return title if title else "General Event"

def parse_time(user_input):
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
    return None

# --- MAIN HANDLER ---
def handle_chat(user_input):
    event_type = detect_event_type(user_input)
    start = parse_time(user_input)

    if not start:
        return "⚠ I couldn’t understand the date/time. Try something like 'tomorrow at 3 PM'."

    end = start + timedelta(minutes=30)

    if check_availability(start, end):
        link = create_event(event_type, start, end)
        return f"✅ Booked **{event_type}** for {start.strftime('%Y-%m-%d %I:%M %p')}. [View in Calendar]({link})"
    else:
        # Try suggesting next free slot
        for i in range(1, 4):
            alt_start = start + timedelta(hours=i)
            alt_end = alt_start + timedelta(minutes=30)
            if check_availability(alt_start, alt_end):
                return f"❌ Busy at requested time. How about **{alt_start.strftime('%Y-%m-%d %I:%M %p')}**?"
        return "❌ Busy at requested time and no nearby slots found. Please suggest another time."

# --- API ---
@app.post("/")
async def chat_api(req: Request):
    data = await req.json()
    user_msg = data.get("message", "")
    reply = handle_chat(user_msg)
    return {"reply": reply}

@app.get("/")
async def root():
    return {"message": "Smart Calendar Bot is running!"}
