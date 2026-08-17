# utils/mistral_client.py
"""
Petite couche d'abstraction autour du SDK Mistral (v1.x, package `mistralai`).

Pourquoi ce fichier existe : `pydantic-ai[mistral]` (utilisé par utils/router.py)
exige `mistralai>=1.2.5`, dont l'API a changé par rapport à l'ancien SDK
(0.4.x) utilisé initialement dans le prototype (`MistralClient`, `ChatMessage`,
`client.chat(...)`). On centralise donc ici les appels chat/embeddings pour
n'avoir qu'un seul endroit à adapter si l'API évolue encore, plutôt que de
dupliquer l'appel SDK dans vector_store.py, sql_tool.py, MistralChat.py et
evaluate_ragas.py.

⚠️ Non exécuté (sandbox indisponible pendant la mission) : à valider avec un
`pip install -r requirements.txt` + un vrai appel avant mise en production.
Si l'API du SDK a encore changé entre-temps, c'est ici qu'il faut corriger.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from mistralai import Mistral

from .config import MISTRAL_API_KEY

logger = logging.getLogger("mistral_client")


class MistralClientError(Exception):
    """Erreur générique lors d'un appel au SDK Mistral (chat ou embeddings)."""
    pass


_client: Optional[Mistral] = None

# Erreurs transitoires côté infra Mistral (indisponibilité momentanée,
# surcharge) : ça vaut le coup de réessayer plutôt que de faire planter tout
# le script (ex: `evaluate_ragas.py` sur 13 questions perdrait tout son
# travail pour un seul 503 isolé). 429 (rate limit) inclus aussi : un léger
# backoff suffit généralement à repasser sous la limite.
_RETRYABLE_STATUS_MARKERS = ("503", "502", "504", "429", "connection", "timeout")
_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 2


def _is_retryable(error: Exception) -> bool:
    msg = str(error).lower()
    return any(marker in msg for marker in _RETRYABLE_STATUS_MARKERS)


def _call_with_retry(fn, description: str):
    last_error: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt < _MAX_RETRIES and _is_retryable(e):
                wait = _BACKOFF_BASE_SECONDS * attempt
                logger.warning(
                    f"{description}: erreur transitoire (tentative {attempt}/{_MAX_RETRIES}), "
                    f"nouvel essai dans {wait}s: {e}"
                )
                time.sleep(wait)
                continue
            logger.error(f"{description}: échec définitif après {attempt} tentative(s): {e}")
            raise MistralClientError(str(e)) from e
    # Ne devrait jamais être atteint (la boucle raise ou return systématiquement)
    raise MistralClientError(str(last_error))


def get_client() -> Mistral:
    """Retourne un client Mistral singleton (réutilisé entre les appels)."""
    global _client
    if _client is None:
        if not MISTRAL_API_KEY:
            raise MistralClientError("MISTRAL_API_KEY manquante.")
        _client = Mistral(api_key=MISTRAL_API_KEY)
    return _client


def chat_complete(model: str, messages: list[dict], temperature: float = 0.1) -> str:
    """
    Appelle le chat completion Mistral (avec retry sur erreurs transitoires).
    `messages` : liste de dicts {"role": "user"/"system"/"assistant", "content": "..."}
    Retourne le texte de la réponse (première completion).
    """
    client = get_client()

    def _do_call():
        response = client.chat.complete(model=model, messages=messages, temperature=temperature)
        if not response.choices:
            raise MistralClientError("Aucune réponse (choices vide) retournée par l'API Mistral.")
        return response.choices[0].message.content

    return _call_with_retry(_do_call, "chat.complete Mistral")


def embed_texts(model: str, texts: list[str]) -> list[list[float]]:
    """Génère les embeddings pour une liste de textes (avec retry). Retourne une liste de vecteurs."""
    client = get_client()

    def _do_call():
        response = client.embeddings.create(model=model, inputs=texts)
        return [d.embedding for d in response.data]

    return _call_with_retry(_do_call, "embeddings.create Mistral")
