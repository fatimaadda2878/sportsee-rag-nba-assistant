# utils/observability.py
"""
Wrapper autour de Pydantic Logfire.

Objectif : instrumenter toute la chaîne RAG/LLM (chunking, embeddings,
recherche vectorielle, appel SQL, appel LLM) sans faire planter l'application
si le token Logfire n'est pas configuré (dev local, CI, environnement offline).

Utilisation dans le reste du code :
    from .observability import logfire
    with logfire.span("mon_etape", **attrs):
        ...
    logfire.info("evenement", **attrs)
"""
import logging
from contextlib import contextmanager

from .config import LOGFIRE_TOKEN, LOGFIRE_DISABLE, LOGFIRE_SERVICE_NAME

logger = logging.getLogger("sportsee_rag.observability")

_logfire_impl = None
_ENABLED = False

if not LOGFIRE_DISABLE:
    try:
        import logfire as _logfire_sdk

        if LOGFIRE_TOKEN:
            _logfire_sdk.configure(
                token=LOGFIRE_TOKEN,
                service_name=LOGFIRE_SERVICE_NAME,
            )
        else:
            # Pas de token : on configure en mode "local only" (affichage console),
            # pratique pour développer sans compte Logfire.
            _logfire_sdk.configure(send_to_logfire=False, service_name=LOGFIRE_SERVICE_NAME)

        _logfire_impl = _logfire_sdk
        _ENABLED = True
        logger.info("Pydantic Logfire initialisé (send_to_logfire=%s).", bool(LOGFIRE_TOKEN))
    except Exception as e:  # pragma: no cover - dépend de l'environnement d'exécution
        logger.warning("Logfire indisponible, bascule sur un no-op logger: %s", e)
        _logfire_impl = None
        _ENABLED = False


class _NoOpSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _NoOpLogfire:
    """Fallback silencieux : mêmes signatures que logfire, mais ne fait rien
    d'autre que logger en local. Permet au reste du code d'appeler
    `logfire.span(...)` / `logfire.info(...)` sans condition partout."""

    @contextmanager
    def span(self, name, **attrs):
        logger.debug("[span] %s %s", name, attrs)
        yield _NoOpSpan()

    def info(self, msg, **attrs):
        logger.info("[logfire:info] %s %s", msg, attrs)

    def warning(self, msg, **attrs):
        logger.warning("[logfire:warning] %s %s", msg, attrs)

    def error(self, msg, **attrs):
        logger.error("[logfire:error] %s %s", msg, attrs)


logfire = _logfire_impl if _ENABLED else _NoOpLogfire()
LOGFIRE_ENABLED = _ENABLED
