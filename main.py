from fastapi import FastAPI, Request
from pydantic import BaseModel
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
import pytz
from langchain.chat_models import ChatHuggingFace
from langchain.schema import HumanMessage
import os

# --- Google Calendar ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = "service_account.json"  # Path to your file

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)
calendar_id = 'primary'

# --- FastAPI app ---
app = FastAPI()

class ChatRequest(BaseModel):
    message: str

# --- Free LLM setup ---
llm = ChatHuggingFace(
    repo_id="HuggingFaceH4/zephyr-7b-beta",  # Or any small free HF model
    huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

# --- Calendar functions ---
def search_slots(start_time, end_time):
    events = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=start_time.isoformat() + 'Z',
        timeMax=end_time.isoformat() + 'Z',
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])
    return events

def create_event(start_time, end_time, summary="Meeting"):
    event = {
        'summary': summary,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'UTC'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'UTC'}
    }
    created = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    return created.get('htmlLink')

@app.post("/chat")
async def chat(req: ChatRequest):
    user_message = req.message

    # Ask LLM to parse intent + time
    sys_prompt = """
    You are a helpful assistant. Extract intended meeting date and time in ISO format.
    If time not mentioned, suggest tomorrow 3 PM UTC.
    Respond only the datetime in ISO format.
    """
    response = llm([
        HumanMessage(content=sys_prompt),
        HumanMessage(content=user_message)
    ])
    try:
        dt = datetime.fromisoformat(response.content.strip())
    except Exception:
        dt = datetime.utcnow() + timedelta(days=1, hours=15)

    end_dt = dt + timedelta(hours=1)

    events = search_slots(dt, end_dt)
    if events:
        return {"reply": f"You're busy at that time. Suggest another time."}

    link = create_event(dt, end_dt)
    return {"reply": f"Booked! Link: {link}"}
