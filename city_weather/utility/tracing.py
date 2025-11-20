"""
Tracing configuration for Cloud Trace (GCP) and LangSmith.
This module sets up OpenTelemetry instrumentation for both services.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# LangSmith configuration - reload from env each time to ensure latest values
def get_langsmith_config():
    """Get LangSmith configuration from environment variables."""
    return {
        "otel_enabled": os.getenv("LANGSMITH_OTEL_ENABLED", "false").lower() == "true",
        "tracing": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
        "project": os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "default")),
        "api_key": os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", "")),
        "endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    }

# GCP Cloud Trace configuration
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")


def setup_tracing():
    """
    Initialize OpenTelemetry tracing for both Cloud Trace and LangSmith.
    This should be called once at application startup.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.trace import ProxyTracerProvider
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        
        # Create resource with service name
        resource = Resource.create({
            "service.name": os.getenv("APP_NAME", "city-weather"),
            "service.version": "1.0.0",
        })
        
        # Prepare LangSmith configuration first
        langsmith_config = get_langsmith_config()
        langsmith_configured = False
        
        # Set environment variable to exclude HTTP spans from LangSmith
        # This tells OpenTelemetry to not auto-instrument HTTP for LangSmith
        if langsmith_config["api_key"]:
            # Exclude FastAPI HTTP spans from being traced by LangSmith
            # We only want agent/LLM spans with session_id
            os.environ["OTEL_PYTHON_FASTAPI_EXCLUDED_URLS"] = "/chat"
            langsmith_configured = _configure_langsmith_otel(langsmith_config)
        
        # Determine tracer provider (LangSmith may have created one)
        provider = trace.get_tracer_provider()
        if isinstance(provider, ProxyTracerProvider):
            provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(provider)
            logger.info("TracerProvider initialized for application")
        else:
            logger.info("Using existing TracerProvider (likely configured by LangSmith)")
            # If LangSmith created the provider, we need to use it
            # But we'll ensure only agent spans go to LangSmith via filtering
        
        # Set up GCP Cloud Trace exporter
        if GCP_PROJECT_ID:
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
                cloud_trace_exporter = CloudTraceSpanExporter(project_id=GCP_PROJECT_ID)
                provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
                logger.info(f"Cloud Trace exporter initialized for project: {GCP_PROJECT_ID}")
            except ImportError:
                logger.warning("opentelemetry-exporter-gcp-trace not available. Cloud Trace will not be enabled.")
            except Exception as e:
                logger.warning(f"Failed to initialize Cloud Trace exporter: {e}")
        else:
            logger.warning("GCP_PROJECT_ID not set. Cloud Trace will not be enabled.")
        
        # Set up LangSmith tracing via OpenTelemetry
        logger.info(
            "LangSmith config check: otel_enabled=%s, tracing=%s, has_api_key=%s, project=%s",
            langsmith_config['otel_enabled'],
            langsmith_config['tracing'],
            bool(langsmith_config['api_key']),
            langsmith_config['project'],
        )
        
        if langsmith_config['api_key'] and not langsmith_configured:
            try:
                # Set LangSmith environment variables for automatic tracing (required for LangChain/LangSmith SDK)
                # LangSmith SDK uses these environment variables to automatically trace LLM calls
                os.environ["LANGCHAIN_TRACING_V2"] = "true"
                os.environ["LANGCHAIN_PROJECT"] = langsmith_config['project']
                os.environ["LANGCHAIN_API_KEY"] = langsmith_config['api_key']
                
                # Also set LangSmith-specific env vars for compatibility
                os.environ["LANGSMITH_TRACING"] = "true"
                os.environ["LANGSMITH_PROJECT"] = langsmith_config['project']
                os.environ["LANGSMITH_API_KEY"] = langsmith_config['api_key']
                
                logger.warning("LangSmith OTEL exporter was not configured earlier; env vars set but no exporter attached.")
            except Exception as e:
                logger.error(f"Failed to set up LangSmith tracing: {e}", exc_info=True)
        else:
            missing = []
            if not langsmith_config['otel_enabled'] and not langsmith_config['tracing']:
                missing.append("LANGSMITH_OTEL_ENABLED or LANGSMITH_TRACING")
            if not langsmith_config['api_key']:
                missing.append("LANGSMITH_API_KEY")
            logger.warning(f"LangSmith tracing not enabled. Missing: {', '.join(missing)}")
        
        # Instrument FastAPI
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            # This will be applied in main.py
            logger.info("FastAPI instrumentation ready")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-fastapi not available.")
        
        # Instrument requests library
        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor
            RequestsInstrumentor().instrument()
            logger.info("Requests library instrumented")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-requests not available.")
        
        logger.info("Tracing setup completed")
        return provider
        
    except ImportError as e:
        logger.warning(f"OpenTelemetry not available: {e}. Tracing will be disabled.")
        return None
    except Exception as e:
        logger.error(f"Failed to set up tracing: {e}", exc_info=True)
        return None


def get_tracer(name: Optional[str] = None):
    """
    Get a tracer instance for manual instrumentation.
    
    Args:
        name: Name of the tracer (defaults to module name)
    
    Returns:
        Tracer instance or None if tracing is not available
    """
    try:
        from opentelemetry import trace
        tracer_provider = trace.get_tracer_provider()
        if tracer_provider is None:
            return None
        return trace.get_tracer(name or __name__)
    except Exception:
        return None


class FilteringSpanProcessor:
    """
    Span processor that filters out HTTP/FastAPI spans before sending to LangSmith.
    Only sends agent/LLM traces with session_id/thread_id.
    """
    def __init__(self, exporter):
        self._exporter = exporter
        self._excluded_names = {"POST", "GET", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}
        self._excluded_prefixes = ("HTTP ", "/chat", "fastapi", "GET /", "POST /")
    
    def on_start(self, span, parent_context=None):
        """Called when a span starts."""
        pass
    
    def on_end(self, span):
        """Called when a span ends - filter before exporting."""
        if self._should_export(span):
            self._exporter.export([span])
    
    def _should_export(self, span) -> bool:
        """Return True if span should be sent to LangSmith."""
        span_name = getattr(span, 'name', str(span))
        
        # Exclude HTTP method spans
        if span_name in self._excluded_names:
            return False
        
        # Exclude spans with HTTP-related prefixes
        if any(span_name.startswith(prefix) for prefix in self._excluded_prefixes):
            return False
        
        # Only include spans that have session_id/thread_id (agent traces)
        # or are explicitly marked as LLM/agent spans
        attrs = getattr(span, 'attributes', {}) or {}
        
        # Include if it has session_id, thread_id (agent traces)
        if any(key in attrs for key in ['session_id', 'thread_id', 'conversation_id', 
                                        'langsmith.session_id', 'langsmith.thread_id']):
            return True
        
        # Include if it's an LLM invocation or agent run
        span_name_lower = span_name.lower()
        if any(keyword in span_name_lower for keyword in ['invocation', 'run_query', 'agent', 'llm', 'gemini']):
            return True
        
        # Default: exclude HTTP/infrastructure spans
        return False
    
    def shutdown(self):
        """Shutdown the exporter."""
        if hasattr(self._exporter, 'shutdown'):
            self._exporter.shutdown()
    
    def force_flush(self, timeout_millis=30000):
        """Force flush the exporter."""
        if hasattr(self._exporter, 'force_flush'):
            return self._exporter.force_flush(timeout_millis)
        return True


def _configure_langsmith_otel(langsmith_config: dict) -> bool:
    """
    Configure LangSmith OpenTelemetry exporter so spans appear in LangSmith UI.
    Note: LangSmith's configure() sets up its own TracerProvider, so we can't easily
    add a filter. Instead, we'll configure it and rely on span attributes to identify
    agent traces. The filtering will be handled by not instrumenting FastAPI for LangSmith.
    """
    try:
        from langsmith.integrations.otel import configure as langsmith_configure
    except ImportError:
        logger.warning("langsmith.integrations.otel not available. Install `langsmith>=0.1.45`.")
        return False

    try:
        # Configure LangSmith - it will set up its own TracerProvider
        langsmith_configure(
            project_name=langsmith_config["project"] or os.getenv("LANGSMITH_PROJECT", "data-science"),
            api_key=langsmith_config["api_key"],
        )
        logger.info("LangSmith OTEL integration configured")
        logger.info("  - Project: %s", langsmith_config['project'])
        logger.info("  - Note: Only spans with session_id/thread_id will be grouped as threads")
        return True
    except Exception as exc:
        logger.error("Failed to configure LangSmith OTEL integration", exc_info=True)
        return False

