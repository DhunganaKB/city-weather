import asyncio
import importlib
import json
import logging
import os
from typing import Optional

from dotenv import find_dotenv, load_dotenv
dotenv_path = find_dotenv()
if dotenv_path:
    load_dotenv(dotenv_path)

from fastapi import FastAPI
from pydantic import BaseModel

from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.genai.types import Content, Part
from multi_tool_agent.agent import root_agent  # ← your custom agent
from utility.helper import (
    save_conversation,
    create_runner,
    build_content_with_history,
    process_event_parts,
)


DB_COLLECTION = os.getenv("DB_COLLECTION", "Weather-Chat")
APP_NAME = os.getenv("APP_NAME", "test_adk_app")
session_service = InMemorySessionService()
artifact_service = InMemoryArtifactService()

# History limits (configurable via env)
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "8000"))

class ChatRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None  # "None" indicates new conversation
    query: str

async def run_query(user_id: str, session_id: Optional[str], query: str):
    session, runner = await create_runner(user_id, session_id)
    content = await build_content_with_history(user_id, session, query)

    final_text = None
    events = []
    async for event in runner.run_async(user_id=session.user_id, session_id=session.id, new_message=content):
        processed = process_event_parts(event)
        if processed:
            events.append(processed)
            if getattr(event, "is_final_response", lambda: False)():
                final_text = processed.get("text") or json.dumps(processed.get("parts", []), ensure_ascii=False)

    try:
        messages = [{"sender": "user", "text": query}] + events
        # save_conversation signature: (user_id, session_id, messages, bot_collection=None)
        await save_conversation(user_id, session.id, messages)
    except Exception:
        logging.exception("Failed to save conversation to Firestore")

    return final_text, session.id

app = FastAPI()

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    POST /chat
    ----------
    {
        "user_id": "1234",
        "session_id": "987",   # or null/new
        "query":     "Hello?"
    }
    """
    final_response, session_id = await run_query(
        user_id=request.user_id,
        session_id=request.session_id if request.session_id not in (None, "null") else None,
        query=request.query,
    )
    return {"response": final_response, "session_id": session_id}
