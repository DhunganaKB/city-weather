import os
import json
from typing import List, Optional

from google.cloud import firestore

# Config from environment
DB_COLLECTION = os.getenv("DB_COLLECTION", "Weather-Chat")
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "travel-concierge")
APP_NAME = os.getenv("APP_NAME", "test_adk_app")

# ADK-related imports and singletons for runner/session creation
import logging
try:
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.runners import Runner
    from multi_tool_agent.agent import root_agent
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
except Exception:
    # ADK may not be available in static analysis; defer errors to runtime
    session_service = None
    artifact_service = None
    Runner = None
    root_agent = None

# History limits (can be overridden via env)
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "8000"))


def get_db():
    """Return an AsyncClient for Firestore."""
    return firestore.AsyncClient(database=FIRESTORE_DATABASE)


def sanitize_session_id(session_id: str) -> str:
    """Sanitize session_id so it's safe as a Firestore collection/document name.
    Removes or replaces characters that would break the path (like slashes).
    """
    if session_id is None:
        return "default"
    return str(session_id).replace("/", "_")


async def load_conversation(user_id: str, session_id: str, bot_collection: Optional[str] = None, db: Optional[firestore.AsyncClient] = None) -> List[dict]:
    """Load messages list from /{bot_collection}/{user_id}/{session_id}/conversation.
    Returns [] when not found or on error.
    """
    bot_collection = bot_collection or DB_COLLECTION
    db = db or get_db()
    session_id = sanitize_session_id(session_id)
    conv_doc = db.collection(bot_collection).document(user_id).collection(session_id).document("conversation")
    try:
        snap = await conv_doc.get()
        if snap and snap.exists:
            data = snap.to_dict() or {}
            return data.get("messages", []) or []
    except Exception:
        # swallow and return empty — caller handles missing history
        return []
    return []


async def save_conversation(user_id: str, session_id: str, messages: List[dict], bot_collection: Optional[str] = None, db: Optional[firestore.AsyncClient] = None, max_conversation_messages: Optional[int] = None) -> None:
    """Append messages to the single conversation document at /{bot_collection}/{user_id}/{session_id}/conversation.
    Optionally trims to the last max_conversation_messages.
    """
    bot_collection = bot_collection or DB_COLLECTION
    db = db or get_db()
    session_id = sanitize_session_id(session_id)
    conv_doc = db.collection(bot_collection).document(user_id).collection(session_id).document("conversation")

    try:
        existing_snap = await conv_doc.get()
        existing = existing_snap.to_dict() or {}
        existing_msgs = existing.get("messages", [])
    except Exception:
        existing_msgs = []

    new_messages = existing_msgs + messages
    if max_conversation_messages:
        new_messages = new_messages[-int(max_conversation_messages):]

    batch = db.batch()
    last_msg = new_messages[-1] if new_messages else {"text": "", "sender": ""}
    batch.set(
        conv_doc,
        {
            "user_id": user_id,
            "session_id": session_id,
            "messages": new_messages,
            "last_message_text": last_msg.get("text", ""),
            "last_message_sender": last_msg.get("sender", ""),
            "last_message_at": firestore.SERVER_TIMESTAMP,
            "message_count": len(new_messages),
            "timestamp": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    try:
        await batch.commit()
    except Exception:
        logging.exception("Failed to commit batch to Firestore")


async def create_runner(user_id: str, session_id: Optional[str]):
    """Spin up an in‑memory ADK Session + Runner and return (session, runner).
    This mirrors the previous implementation that lived in main.py.
    """
    if session_service is None or artifact_service is None or Runner is None or root_agent is None:
        raise RuntimeError("ADK dependencies are not available in this environment")
    try:
        session = await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    except Exception as e:
        if e.__class__.__name__ == "AlreadyExistsError":
            session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
            if session is None:
                raise
        else:
            raise
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service, artifact_service=artifact_service)
    return session, runner


async def build_content_with_history(user_id: str, session, query: str) -> 'Content':
    """Load prior conversation and build a Content object with history prepended if available."""
    try:
        prior_messages = await load_conversation(DB_COLLECTION, user_id, session.id)
    except Exception:
        logging.exception("Failed to load prior messages")
        prior_messages = []

    if prior_messages:
        prior_messages = prior_messages[-MAX_HISTORY_MESSAGES:]
        history_lines = []
        for m in prior_messages:
            sender = m.get("sender", "")
            text = m.get("text")
            if text:
                history_lines.append(f"{sender}: {text}")
            else:
                parts = m.get("parts", [])
                part_texts = []
                for p in parts:
                    ptype = p.get("type")
                    if ptype == "text":
                        part_texts.append(p.get("text", ""))
                    elif ptype == "function_call":
                        part_texts.append(f"[function_call name={p.get('name')} args={p.get('args')}]")
                    elif ptype == "function_response":
                        part_texts.append(f"[function_response name={p.get('name')} response={p.get('response')}]")
                    else:
                        part_texts.append(str(p.get("repr", p)))
                history_lines.append(f"{sender}: {' | '.join(part_texts)}")

        history_text = "History:\n" + "\n".join(history_lines) + "\n\n"
        if len(history_text) > MAX_HISTORY_CHARS and history_lines:
            while history_lines and len("History:\n" + "\n".join(history_lines) + "\n\n") > MAX_HISTORY_CHARS:
                history_lines.pop(0)
            history_text = "History:\n" + "\n".join(history_lines) + "\n\n"
        content_text = history_text + "User: " + query
    else:
        content_text = query
    # Import Content/Part lazily to avoid circular/static import issues
    try:
        from google.genai.types import Content
    except Exception:
        Content = None
    if Content is None:
        # create a simple placeholder object with expected attributes for runtime tests
        class _C:
            def __init__(self, role, parts):
                self.role = role
                self.parts = parts
        return _C(role="user", parts=[{"text": content_text}])
    return Content(role="user", parts=[__import__('google.genai.types', fromlist=['Part']).Part(text=content_text)])


def process_event_parts(event) -> Optional[dict]:
    """Return a dict with sender, text, parts for a single event, or None."""
    if not (getattr(event, 'content', None) and getattr(event.content, 'parts', None)):
        return None
    parts_list = []
    text_parts = []
    for part in event.content.parts:
        if getattr(part, "text", None):
            parts_list.append({"type": "text", "text": part.text})
            text_parts.append(part.text)
        elif getattr(part, "function_call", None):
            fc = part.function_call
            try:
                args_val = fc.args
            except Exception:
                args_val = getattr(fc, "args", str(fc))
                logging.exception("function_call.args access error")
            parts_list.append({
                "type": "function_call",
                "name": getattr(fc, "name", None),
                "id": getattr(fc, "id", None),
                "args": args_val,
            })
        elif getattr(part, "function_response", None):
            fr = part.function_response
            try:
                resp_val = fr.response
            except Exception:
                resp_val = getattr(fr, "response", str(fr))
                logging.exception("function_response.response access error")
            parts_list.append({
                "type": "function_response",
                "name": getattr(fr, "name", None),
                "id": getattr(fr, "id", None),
                "response": resp_val,
            })
        else:
            try:
                part_repr = str(part)
            except Exception:
                part_repr = repr(part)
                logging.exception("part repr error")
            parts_list.append({"type": "unknown", "repr": part_repr})

    concatenated_text = "\n".join(text_parts) if text_parts else None
    sender = getattr(event, "role", "agent") or "agent"
    return {"sender": sender, "text": concatenated_text, "parts": parts_list}
