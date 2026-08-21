# utils/router.py
"""
Routeur de requêtes : décide si une question utilisateur nécessite le SQL Tool
(données chiffrées : stats, comparaisons, agrégations) ou uniquement la
recherche vectorielle (contexte qualitatif : rapports, actualités, analyses
texte issues des archives Reddit/rapports).

Implémenté avec Pydantic AI : la sortie du classifieur est un modèle Pydantic
strict (QueryRoute), ce qui garantit que l'agent en aval reçoit toujours une
décision structurée et valide (jamais un texte libre à re-parser).

Un filet de sécurité heuristique (mots-clés + regex numériques) est appliqué
en complément : si le LLM échoue ou est indisponible, on retombe sur cette
règle simple plutôt que de planter.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field, model_validator
from pydantic_ai import Agent

from .config import MISTRAL_API_KEY, MODEL_NAME
from .observability import logfire

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("router")


class QueryRoute(BaseModel):
    """Décision de routage structurée, validée par Pydantic."""
    needs_sql: bool = Field(..., description="True si la question porte sur des données chiffrées/statistiques")
    needs_text_context: bool = Field(
        default=True,
        description="True si la question bénéficie aussi du contexte texte (rapports/archives)"
    )
    needs_plot: bool = Field(
        default=False,
        description="True si la question demande explicitement une visualisation/graphique (ajouté le 21/08/2026)"
    )
    reasoning: str = Field(..., min_length=1, max_length=300)

    @model_validator(mode="after")
    def _plot_requires_sql(self) -> "QueryRoute":
        """
        Garde-fou (corrigé le 21/08/2026) : un graphique n'a de sens que sur
        des données chiffrées. Bug observé en test réel : le routeur LLM
        pouvait renvoyer needs_plot=True avec needs_sql=False, ce qui
        empêchait MistralChat.py d'exécuter le SQL Tool en amont — le texte
        de réponse affirmait alors "donnée non disponible" (voire inventait
        un exemple hypothétique) alors que le PlotTool, lui, ré-exécutait le
        SQL Tool de son côté (voir plot_tool.py::run_plot_tool) et affichait
        un vrai graphique : un texte et un graphique contradictoires dans la
        même réponse. On force donc l'invariant ici, au niveau du modèle,
        pour qu'il tienne quelle que soit la source de la décision (LLM ou
        heuristique de repli).
        """
        if self.needs_plot and not self.needs_sql:
            self.needs_sql = True
        return self


_HEURISTIC_KEYWORDS = re.compile(
    r"(pourcentage|%|moyenne|meilleur|classement|top\s?\d|combien|statistiques?|"
    r"rebonds?|passes?|points?|3\s?points?|domicile|ext[ée]rieur|comparer?|compare)",
    re.IGNORECASE,
)
_HEURISTIC_NUMBERS = re.compile(r"\d")

# needs_plot : ajouté le 21/08/2026 (PlotTool). Mots-clés explicites de
# demande de visualisation — volontairement restrictif (un graphique n'est
# généré que si demandé clairement) plutôt qu'un déclenchement automatique
# sur toute question chiffrée.
_PLOT_KEYWORDS = re.compile(
    r"(graphique|graph|visualise|visualisation|montre.*(évolution|evolution)|"
    r"trace|courbe|camembert|diagramme|répartition|repartition)",
    re.IGNORECASE,
)


def _heuristic_route(question: str) -> QueryRoute:
    """Filet de sécurité sans appel LLM : mots-clés statistiques ou chiffres présents."""
    needs_sql = bool(_HEURISTIC_KEYWORDS.search(question)) or bool(_HEURISTIC_NUMBERS.search(question))
    needs_plot = bool(_PLOT_KEYWORDS.search(question))
    return QueryRoute(
        needs_sql=needs_sql or needs_plot,  # un graphique nécessite forcément des données chiffrées
        needs_text_context=True,
        needs_plot=needs_plot,
        reasoning="Décision heuristique (fallback, sans appel LLM).",
    )


_router_agent: Optional[Agent] = None


def _get_router_agent() -> Agent:
    global _router_agent
    if _router_agent is None:
        # NB (corrigé le 17/08/2026) : pydantic-ai a renommé le paramètre de
        # sortie structurée `result_type` -> `output_type` (le champ `.data`
        # du résultat est devenu `.output`, voir route_query ci-dessous).
        # L'ancien nom ne levait pas d'erreur bloquante mais provoquait un
        # échec systématique de l'agent, silencieusement rattrapé par le
        # fallback heuristique : le routage LLM ne se déclenchait donc
        # jamais en pratique tant que ce n'était pas corrigé.
        _router_agent = Agent(
            f"mistral:{MODEL_NAME}",
            output_type=QueryRoute,
            system_prompt=(
                "Tu classes les questions d'un chatbot d'analyse NBA. "
                "needs_sql=True si répondre nécessite des chiffres/statistiques "
                "précis (points, rebonds, %, comparaisons, classements, agrégations). "
                "needs_text_context=True si le contexte qualitatif (rapports, avis, "
                "actualités) reste utile en complément. "
                "needs_plot=True UNIQUEMENT si l'utilisateur demande explicitement "
                "une visualisation/un graphique (mots comme 'graphique', 'montre "
                "l'évolution', 'trace', 'compare visuellement') — jamais par défaut "
                "pour une simple question chiffrée. Sois concis."
            ),
        )
    return _router_agent


def route_query(question: str) -> QueryRoute:
    """Détermine si la question nécessite le SQL Tool, la recherche vectorielle, ou les deux."""
    with logfire.span("route_query", question=question):
        if not MISTRAL_API_KEY:
            logger.warning("MISTRAL_API_KEY absente, routage heuristique utilisé.")
            return _heuristic_route(question)

        try:
            # Streamlit exécute le script dans un thread dédié
            # ('ScriptRunner.scriptThread') sans event loop asyncio par défaut
            # (Python 3.10+ ne le crée plus implicitement) : pydantic-ai
            # (agent.run_sync -> asyncio.get_event_loop()) plante sinon avec
            # "There is no current event loop in thread ...". On s'assure
            # qu'un event loop existe pour le thread courant avant l'appel.
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())

            agent = _get_router_agent()
            result = agent.run_sync(question)
            route = result.output
            logfire.info(
                "query_routed", question=question, needs_sql=route.needs_sql,
                needs_text_context=route.needs_text_context, needs_plot=route.needs_plot,
            )
            return route
        except Exception as e:
            logger.warning(f"Échec du routage via Pydantic AI, fallback heuristique: {e}")
            logfire.info("router_fallback_heuristic", error=str(e))
            return _heuristic_route(question)
