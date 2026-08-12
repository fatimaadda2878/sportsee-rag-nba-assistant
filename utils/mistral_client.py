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
from typing import Optional

from mistralai import Mistral

from .config import MISTRAL_API_KEY

logger = logging.getLogger("mistral_client")


class MistralClientError(Exception):
    """Erreur générique lors d'un appel au SDK Mistral (chat ou embeddings)."""
    pass


_client: Optional[Mistral] = None


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
    Appelle le chat completion Mistral.
    `messages` : liste de dicts {"role": "user"/"system"/"assistant", "content": "..."}
    Retourne le texte de la réponse (première completion).
    """
    client = get_client()
    try:
        response = client.chat.complete(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'appel chat.complete Mistral: {e}")
        raise MistralClientError(str(e)) from e

    if not response.choices:
        raise MistralClientError("Aucune réponse (choices vide) retournée par l'API Mistral.")
    return response.choices[0].message.content


def embed_texts(model: str, texts: list[str]) -> list[list[float]]:
    """Génère les embeddings pour une liste de textes. Retourne une liste de vecteurs."""
    client = get_client()
    try:
        response = client.embeddings.create(model=model, inputs=texts)
    except Exception as e:
        logger.error(f"Erreur lors de l'appel embeddings.create Mistral: {e}")
        raise MistralClientError(str(e)) from e
    return [d.embedding for d in response.data]
