import os
import json
from datetime import datetime, timedelta
import pytz

from fastapi import FastAPI, Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
import dateparser

from huggingface_hub import InferenceClient
from langchain_core.language_models import LLM
from langchain_core.outputs import Generation, LLMResult
from pydantic import PrivateAttr

# --- GOOGLE CALENDAR SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
credentials = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)
calendar_service = build('calendar', 'v3', credentials=credentials)
calendar_id = 'chalasaniajitha@gmail.com'  # Replace with your calendar ID

# --- FASTAPI ---
app = FastAPI()

# --- CUSTOM LANGCHAIN LLM ---
class HuggingFaceCustomLLM(LLM):
    repo_id: str
    _client: InferenceClient = PrivateAttr()

    def __init__(self, repo_id: str, token: str, **kwargs):
        super().__init__(repo_id=repo_id, **kwargs)
        self._client = InferenceClient(token=token)
        self.repo_id = repo_id

    @property
    def _llm_type(self) -> str:
        return "huggingface_custom"

    def _call(self, prompt: str, stop=None, run_manager=None, **kwargs) -> str:
        response = self._client.text_generation(
            repo_id=self.repo_id,
            prompt=prompt,
            max_new_tokens=200
        )
        return response.strip()

    def generate(self, prompts, stop=None, **kwargs) -> LLMResult:
        generations = []
        for prompt in prompts:
            text = self._call(prompt, stop=stop, **kwargs)
            generations.append([Generation(text=text)])
        return LLMResult(generations=generations)

# --- Instantiate LLM ---
llm = HuggingFaceCustomLLM(
    repo_id="HuggingFaceH4/zephyr-7b-beta",
    token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

# --- Helpers ---
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
    prompt = f"{system_prompt}\nUser: {user_input}"
    result = llm.generate([prompt])
    reply = result.generations[0][0].text
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
            return f"{title.capitalize()} booked! [View here]({link})"

    elif intent == "check_availability":
        suggestion = suggest_slot()
        return f"You're free at {suggestion}. Shall I book it?"

    else:
        # fallback to LLM chat reply
        result = llm.generate([user_input])
        return result.generations[0][0].text.strip()

# --- ROUTES ---
@app.post("/")
async def chat_api(req: Request):
    data = await req.json()
    user_message = data.get("message", "")
    response = handle_chat(user_message)
    return {"reply": response}

@app.get("/")
async def root():
    return {"message": "Smart Calendar Bot is running!"}
