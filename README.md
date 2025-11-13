# Persistent Memory with Firestore (GCP)

This project is a small **FastAPI** application that demonstrates how to use
**Google Cloud Firestore** as persistent memory for an agent built with the
Google ADK framework. It can fetch real-time weather for a given city and
store conversation history per user session.

---

## Features

- FastAPI-based `/chat` endpoint
- Real-time weather lookup for a given city
- Per-user, per-session conversation history
- Persistent memory using Firestore (GCP native NoSQL database)

---

## Environment Setup

1. **Google Cloud credentials**

   Configure authentication using one of:

   - Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable, or
   - Run:

     ```bash
     gcloud auth application-default login
     ```

2. **Optional `.env` configuration**

   Create a `.env` file to override defaults:

   - `DB_COLLECTION` – Firestore collection name
   - `MAX_HISTORY_MESSAGES` – Maximum number of messages to store per session
   - `MAX_HISTORY_CHARS` – Maximum total character length of stored history
   - `APP_NAME` – Application name (for logs/identification)

---

## How to Run

1. Install dependencies:

   ```bash
   pip install -r requirements.txt

2. Start the FastAPI app with Uvicorn:
    cd city-weather
    uvicorn deployment.main:app --reload

3. Send a POST request to /chat:

    POST /chat
    Content-Type: application/json

    {
    "user_id":    "1234",
    "session_id": "987",      
    "query":      "Hello"
    }

## Firestore Layout

    Conversation documents are stored under:

    /{DB_COLLECTION}/{user_id}/{session_id}/conversation
