import asyncio
import importlib
import json
import logging
import os
import sys
from typing import Optional

# Configure logging first, before loading .env
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from dotenv import find_dotenv, load_dotenv
import pathlib

# Load .env file from project root (parent of city_weather directory)
# This ensures .env is found regardless of where uvicorn is run from
project_root = pathlib.Path(__file__).parent.parent.parent
env_path = project_root / ".env"
env_loaded = False

if env_path.exists():
    load_dotenv(env_path, override=True)
    logger.info(f"✓ Loaded .env from: {env_path}")
    env_loaded = True
else:
    # Fallback to find_dotenv() behavior
    dotenv_path = find_dotenv()
    if dotenv_path:
        load_dotenv(dotenv_path, override=True)
        logger.info(f"✓ Loaded .env from: {dotenv_path}")
        env_loaded = True
    else:
        logger.warning("⚠ No .env file found!")
        logger.warning(f"  Expected location: {env_path}")
        logger.warning("  Using environment variables only.")
        logger.warning("  To create .env file: cp .env.example .env")

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
from utility.tracing import setup_tracing, get_tracer


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
    tracer = get_tracer(__name__)
    span = None
    
    # Use the actual session_id from the session object (will be set after create_runner)
    # For now, use the provided session_id or generate a placeholder
    actual_session_id = str(session_id) if session_id else "new"
    
    if tracer:
        span = tracer.start_span("run_query")
        
        # Set standard attributes
        span.set_attribute("user_id", user_id)
        span.set_attribute("session_id", actual_session_id)
        span.set_attribute("query", query)
        
        # Set LangSmith-recognized metadata attributes for thread grouping
        # LangSmith recognizes: session_id, thread_id, or conversation_id in span attributes
        span.set_attribute("thread_id", actual_session_id)
        span.set_attribute("conversation_id", actual_session_id)
        # LangSmith also recognizes namespaced attributes
        span.set_attribute("langsmith.session_id", actual_session_id)
        span.set_attribute("langsmith.thread_id", actual_session_id)
    
    try:
        session, runner = await create_runner(user_id, session_id)
        
        # Update session_id attributes with the actual session.id from ADK
        actual_session_id = str(session.id)
        if span:
            span.set_attribute("session_id", actual_session_id)
            span.set_attribute("thread_id", actual_session_id)
            span.set_attribute("conversation_id", actual_session_id)
            span.set_attribute("langsmith.session_id", actual_session_id)
            span.set_attribute("langsmith.thread_id", actual_session_id)
        
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

        if span:
            span.set_attribute("response_length", len(final_text) if final_text else 0)
            span.set_attribute("events_count", len(events))
        
        return final_text, session.id
    except Exception as e:
        if span:
            from opentelemetry.trace import Status, StatusCode
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
        raise
    finally:
        if span:
            span.end()

app = FastAPI()

# Initialize tracing at startup
@app.on_event("startup")
async def startup_event():
    """Initialize tracing on application startup."""
    logger.info("=" * 60)
    logger.info("Starting application initialization...")
    logger.info("=" * 60)
    
    # Log environment status
    if env_loaded:
        logger.info("Environment: .env file loaded successfully")
    else:
        logger.warning("Environment: No .env file found - using system environment variables")
    
    # Initialize tracing
    logger.info("Initializing tracing (Cloud Trace + LangSmith)...")
    try:
        setup_tracing()
        logger.info("Tracing initialization completed")

        # langsmith_configure(
        #     project_name=os.getenv("LANGSMITH_PROJECT", "data-science"),
        #     api_key=os.getenv("LANGSMITH_API_KEY"),
        # )
    except Exception as e:
        logger.error(f"Failed to initialize tracing: {e}", exc_info=True)
    
    # Instrument FastAPI with OpenTelemetry
    # Note: HTTP spans will go to Cloud Trace
    # LangSmith will receive agent spans (with session_id) but HTTP spans are filtered
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        # Exclude /chat from auto-instrumentation to prevent POST spans in LangSmith
        # We manually create spans for agent operations with session_id
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/chat")
        logger.info("✓ FastAPI instrumented with OpenTelemetry")
        logger.info("  - /chat route excluded from auto-instrumentation")
        logger.info("  - Agent spans (with session_id) will appear in LangSmith as threads")
        logger.info("  - HTTP spans go to Cloud Trace only")
    except ImportError:
        logger.warning("⚠ FastAPI instrumentation not available")
    except Exception as e:
        logger.warning(f"⚠ Failed to instrument FastAPI: {e}")
    
    logger.info("=" * 60)
    logger.info("Application startup complete")
    logger.info("=" * 60)

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
