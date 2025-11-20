# City Weather Agent with Firestore Memory, Logging, and Observability

A production-ready **FastAPI** application demonstrating a weather agent built with **Google ADK** framework. Features persistent conversation memory, comprehensive logging, and full observability across both **LangSmith** and **Google Cloud Trace Explorer**.

---

## 🎯 Key Features

### 1. 🔥 **Firestore Persistent Memory**
- **Per-user, per-session conversation history** stored in Google Cloud Firestore
- Automatic conversation context retrieval for multi-turn dialogues
- Configurable history limits (messages and character count)
- Seamless session management with Google ADK

### 2. 📊 **Comprehensive Logging**
- Structured logging with timestamps and log levels
- Application startup and initialization logging
- Error tracking and exception logging
- Environment variable loading verification
- Request/response logging for debugging

### 3. 🔍 **Agent Observability in LangSmith**
- **Full LLM call tracing** with OpenTelemetry integration
- **Thread/Session grouping** - Traces automatically grouped by `session_id`
- **Smart filtering** - Only agent traces (HTTP POST spans excluded)
- Real-time observability for AI/ML workflows
- View and analyze agent behavior in [LangSmith Dashboard](https://smith.langchain.com)

### 4. 📈 **Distributed Tracing in GCP Trace Explorer**
- **Complete request tracing** via FastAPI instrumentation
- **Agent tool call tracing** (geocoding, weather API calls)
- **Firestore operation tracing** for database interactions
- **Performance monitoring** with latency and error tracking
- View traces in [Google Cloud Trace Explorer](https://console.cloud.google.com/traces)

---

## 🏗️ Architecture Overview

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ HTTP POST /chat
       ▼
┌─────────────────────────────────────┐
│      FastAPI Application            │
│  ┌──────────────────────────────┐  │
│  │  Google ADK Agent            │  │
│  │  - Weather Tool               │  │
│  │  - Geocoding Tool             │  │
│  └──────────────────────────────┘  │
└──────┬──────────────────┬───────────┘
       │                  │
       ▼                  ▼
┌──────────────┐   ┌──────────────────┐
│  Firestore  │   │  OpenTelemetry    │
│  (Memory)   │   │  ┌──────────────┐ │
└──────────────┘   │  │ Cloud Trace │ │
                   │  │ LangSmith   │ │
                   │  └──────────────┘ │
                   └──────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Google Cloud Project with Firestore enabled
- LangSmith account (optional, for agent observability)
- Google Cloud credentials configured

### Installation

1. **Clone and navigate to the project:**
   ```bash
   cd city-weather
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials (see Environment Setup below)
   ```

4. **Run the application:**
   ```bash
   cd city_weather
   uvicorn deployment.main:app --reload
   ```

5. **Test the endpoint:**
   ```bash
   curl -X POST http://127.0.0.1:8000/chat \
     -H "Content-Type: application/json" \
     -d '{
       "user_id": "1234",
       "session_id": "test-session",
       "query": "What is the weather in New York?"
     }'
   ```

---

## ⚙️ Environment Setup

### 1. Google Cloud Credentials

Configure authentication using one of:

- Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable, or
- Run:
  ```bash
  gcloud auth application-default login
  ```

### 2. Create `.env` File

Your `.env` file **MUST** be in the **project root directory** (same level as `requirements.txt`):

```
city-weather/
├
├── .env.example           ← Example template
├── requirements.txt
├── README.md
└── city_weather/
    └── ...
```

#### Required Configuration

**For Firestore (Memory):**
```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
FIRESTORE_DATABASE=your-database-name  # Optional, defaults to travel-concierge
DB_COLLECTION=Weather-Chat             # Optional, defaults to Weather-Chat
```

**For GCP Trace Explorer:**
```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
# OR
GCP_PROJECT_ID=your-gcp-project-id
```

**For LangSmith Observability:**
```bash
LANGSMITH_OTEL_ENABLED=true
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=your-project-name
LANGSMITH_API_KEY=lsv2_pt_01...  # Get from https://smith.langchain.com/settings
```

**Optional Configuration:**
```bash
APP_NAME=city-weather
MAX_HISTORY_MESSAGES=20
MAX_HISTORY_CHARS=8000
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

#### Verify Configuration

After creating `.env`, restart the application and look for:

```
✓ Loaded .env from: /path/to/city-weather/.env
Environment: .env file loaded successfully
Cloud Trace exporter initialized for project: your-project-id
LangSmith OTEL integration configured
```

---

## 📖 Usage

### API Endpoint

**POST** `/chat`

**Request:**
```json
{
  "user_id": "1234",
  "session_id": "conversation-1",  // Optional - creates new if not provided
  "query": "What's the weather in Paris?"
}
```

**Response:**
```json
{
  "response": "In Paris, France it is 18.5 °C with wind speed 12.3 km/h. Local time is 2025-11-19 14:30:00 CET.",
  "session_id": "conversation-1"  // Use this for tracking in LangSmith
}
```

### Multi-Turn Conversations

The agent maintains conversation context across multiple requests using the same `session_id`:

```bash
# First request
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "1234",
    "session_id": "my-conversation",
    "query": "What is the weather in Tokyo?"
  }'

# Follow-up request (uses conversation history)
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "1234",
    "session_id": "my-conversation",
    "query": "What about New York?"
  }'
```

---

## 💾 Firestore Memory

### Storage Structure

Conversation history is stored in Firestore with the following structure:

```
/{DB_COLLECTION}/{user_id}/{session_id}/conversation
```

**Example:**
```
/Weather-Chat/user-1234/session-5678/conversation
```

### Document Schema

```json
{
  "user_id": "user-1234",
  "session_id": "session-5678",
  "messages": [
    {
      "sender": "user",
      "text": "What's the weather in Paris?"
    },
    {
      "sender": "agent",
      "text": "In Paris, France it is 18.5 °C...",
      "parts": [...]
    }
  ],
  "last_message_text": "In Paris, France it is 18.5 °C...",
  "last_message_sender": "agent",
  "last_message_at": "2025-11-19T14:30:00Z",
  "message_count": 2,
  "timestamp": "2025-11-19T14:30:00Z"
}
```

### Configuration

- **`MAX_HISTORY_MESSAGES`**: Maximum number of messages to load per session (default: 20)
- **`MAX_HISTORY_CHARS`**: Maximum total character length of history (default: 8000)

---

## 📊 Logging

### Log Levels and Format

The application uses structured logging with the following format:

```
2025-11-19 14:30:00,123 - module.name - INFO - Message content
```

### Key Log Events

**Application Startup:**
```
============================================================
Starting application initialization...
============================================================
✓ Loaded .env from: /path/to/.env
Environment: .env file loaded successfully
Initializing tracing (Cloud Trace + LangSmith)...
Cloud Trace exporter initialized for project: your-project-id
LangSmith OTEL integration configured
✓ FastAPI instrumented with OpenTelemetry
============================================================
Application startup complete
============================================================
```

**Request Processing:**
- User query logging
- Session creation/retrieval
- Agent execution
- Firestore save operations
- Error tracking with stack traces

### Viewing Logs

Logs are output to stdout and can be:
- Viewed in terminal when running with `uvicorn`
- Collected by Google Cloud Logging (if deployed to GCP)
- Redirected to files for production deployments

---

## 🔍 LangSmith Agent Observability

### Features

- **Automatic LLM Tracing**: All Google ADK/GenAI calls are automatically traced
- **Thread Grouping**: Traces grouped by `session_id` for conversation tracking
- **Smart Filtering**: Only agent traces appear (HTTP infrastructure spans excluded)
- **Real-time Monitoring**: View agent behavior as it happens
- **Performance Metrics**: Token usage, latency, and cost tracking

### Accessing LangSmith

1. **Navigate to your project**: [LangSmith Dashboard](https://smith.langchain.com)
2. **Select your project**: Use the project name from `LANGSMITH_PROJECT`
3. **View traces**: Click on "Runs" or "Threads" tab
4. **Filter by session**: Search for `session_id: your-session-id` or `thread_id: your-session-id`

### Thread/Session Tracking

All traces with the same `session_id` are automatically grouped into threads:

**Request:**
```json
{
  "user_id": "1234",
  "session_id": "my-thread-1",
  "query": "What's the weather in Paris?"
}
```

**In LangSmith:**
- Search for `session_id: my-thread-1` or `thread_id: my-thread-1`
- All traces for this conversation appear in the same thread
- View the complete conversation flow with all LLM calls

### What Gets Traced

✅ **Included:**
- Agent execution (`run_query` spans)
- LLM invocations
- Tool calls (geocoding, weather API)
- All spans with `session_id`/`thread_id` attributes

❌ **Excluded:**
- HTTP POST/GET requests
- FastAPI infrastructure spans
- Generic HTTP method spans

---

## 📈 GCP Trace Explorer

### Features

- **Complete Request Tracing**: Full HTTP request lifecycle
- **Agent Tool Tracing**: Geocoding and weather API calls
- **Database Operations**: Firestore read/write operations
- **Performance Analysis**: Latency breakdown and bottleneck identification
- **Error Tracking**: Failed requests and exceptions

### Accessing Trace Explorer

1. **Navigate to**: [Google Cloud Console - Trace Explorer](https://console.cloud.google.com/traces)
2. **Select your project**: Use the project from `GOOGLE_CLOUD_PROJECT`
3. **View traces**: Browse by service, operation, or time range
4. **Analyze performance**: Click on traces to see detailed span breakdown

### Trace Structure

```
HTTP POST /chat
├── run_query
│   ├── create_runner
│   ├── build_content_with_history
│   │   └── load_conversation (Firestore)
│   ├── runner.run_async
│   │   ├── LLM: gemini-2.0-flash
│   │   └── get_city_weather_and_time
│   │       ├── geocode_city (HTTP request)
│   │       └── get_weather_for_coords (HTTP request)
│   └── save_conversation (Firestore)
```

### What Gets Traced

✅ **Included:**
- All HTTP requests (POST, GET, etc.)
- Agent operations
- Tool calls
- Firestore operations
- External API calls

---

## 🛠️ Troubleshooting

### LangSmith Not Showing Traces

1. **Verify `.env` file location**: Must be in project root
2. **Check environment variables**: Look for startup log messages
3. **Verify API key**: Get from [LangSmith Settings](https://smith.langchain.com/settings)
4. **Check project name**: Must match your LangSmith project
5. **Restart application**: After changing `.env`, fully restart uvicorn

### Cloud Trace Not Showing Traces

1. **Verify GCP project ID**: Check `GOOGLE_CLOUD_PROJECT` in `.env`
2. **Check credentials**: Ensure `gcloud auth application-default login` completed
3. **Verify Firestore enabled**: Cloud Trace requires active GCP project
4. **Check permissions**: Service account needs Cloud Trace Writer role

### Firestore Memory Not Working

1. **Verify database exists**: Check Firestore database in GCP Console
2. **Check collection name**: Verify `DB_COLLECTION` matches your setup
3. **Review permissions**: Service account needs Firestore read/write access
4. **Check logs**: Look for Firestore error messages in application logs

---

## 📁 Project Structure

```
city-weather/
├── .env                    # Environment variables (create from .env.example)
├── .env.example           # Environment variable template
├── requirements.txt       # Python dependencies
├── README.md             # This file
└── city_weather/
    ├── deployment/
    │   └── main.py       # FastAPI application and endpoints
    ├── multi_tool_agent/
    │   └── agent.py      # Weather agent with tools
    └── utility/
        ├── helper.py     # Firestore operations and session management
        └── tracing.py    # OpenTelemetry tracing configuration
```

---

## 🔗 Useful Links

- [Google Cloud Firestore Documentation](https://cloud.google.com/firestore/docs)
- [Google Cloud Trace Explorer](https://console.cloud.google.com/traces)
- [LangSmith Dashboard](https://smith.langchain.com)
- [Google ADK Documentation](https://cloud.google.com/vertex-ai/docs/adk)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)

---

## 📝 License

This project is provided as-is for educational and demonstration purposes.

---

## 🤝 Contributing

This is a demonstration project. For production use, consider:
- Adding authentication and authorization
- Implementing rate limiting
- Adding input validation and sanitization
- Setting up CI/CD pipelines
- Adding comprehensive error handling
- Implementing monitoring and alerting
