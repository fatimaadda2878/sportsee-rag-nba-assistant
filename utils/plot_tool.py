# utils/plot_tool.py
"""
PlotTool : génère dynamiquement un graphique (barres/courbe/camembert) à
partir d'une question en langage naturel portant sur des statistiques NBA.

Ajouté le 21/08/2026 à la demande de Sarah ("génération dynamique de
graphiques avec un PlotTool personnalisé").

Choix de conception (volontairement différent d'un agent LangChain "libre") :
le PlotTool ne génère JAMAIS lui-même les valeurs numériques du graphique. Il
réutilise exclusivement les lignes déjà récupérées et validées par le SQL
Tool (utils/sql_tool.py) — qui possède déjà ses propres garde-fous
anti-hallucination. Un seul choix reste délégué au LLM (ou à une heuristique
de repli sans appel API, sur le même principe que utils/router.py) : le TYPE
de graphique à produire (barres / courbe / camembert). Cela évite d'ouvrir un
second point d'hallucination de données dans le pipeline, ce qui aurait
contredit la philosophie de sécurité du reste du projet.
"""
from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # pas d'affichage interactif : rendu serveur (Streamlit)
import matplotlib.pyplot as plt

from .schemas import PlotToolInput, PlotToolOutput, SQLToolOutput
from .observability import logfire

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("plot_tool")

PLOTS_DIR = Path("data") / "plots"
MAX_POINTS = 15  # lisibilité du graphique (cohérent avec rows_preview du SQL Tool, déjà limité à 20)


# ============================================================
# Choix du type de graphique (heuristique mots-clés, sans appel LLM)
#
# Même philosophie que utils/router.py::_heuristic_route : un choix de
# présentation (pas une donnée) n'a pas besoin d'un appel LLM pour rester
# fiable, rapide et testable sans API — un point important la veille d'une
# démo en direct.
# ============================================================
_LINE_KEYWORDS = re.compile(r"(évolution|evolution|tendance|progression|au fil|courbe)", re.IGNORECASE)
_PIE_KEYWORDS = re.compile(r"(répartition|repartition|part de|proportion|camembert)", re.IGNORECASE)


def _choose_chart_type(question: str) -> str:
    if _LINE_KEYWORDS.search(question):
        return "line"
    if _PIE_KEYWORDS.search(question):
        return "pie"
    return "bar"  # par défaut : comparaisons, classements, top N


def _extract_labels_and_values(sql_output: SQLToolOutput) -> tuple[list[str], list[float], str]:
    """
    Choisit une colonne "label" (texte) et une colonne "valeur" (numérique)
    parmi les lignes déjà récupérées par le SQL Tool. Ne fabrique aucune
    donnée : si aucune colonne numérique n'est trouvée, lève ValueError
    (traduit en erreur explicite par run_plot_tool, pas en graphique inventé).
    """
    rows = sql_output.rows_preview[:MAX_POINTS]
    if not rows:
        raise ValueError("Aucune ligne de résultat à représenter.")

    columns = sql_output.columns
    label_col = None
    value_col = None
    for col in columns:
        sample = rows[0].get(col)
        if label_col is None and isinstance(sample, str):
            label_col = col
        elif value_col is None and isinstance(sample, (int, float)) and not isinstance(sample, bool):
            value_col = col

    if value_col is None:
        raise ValueError("Aucune colonne numérique dans le résultat SQL : impossible de tracer un graphique.")

    labels = [str(row.get(label_col, i)) for i, row in enumerate(rows)] if label_col else [str(i) for i in range(len(rows))]
    values = [float(row.get(value_col, 0) or 0) for row in rows]
    return labels, values, value_col


def _render_chart(chart_type: str, labels: list[str], values: list[float], title: str) -> str:
    """Génère le graphique avec matplotlib et retourne une chaîne base64 (PNG)."""
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if chart_type == "line":
        ax.plot(labels, values, marker="o", color="#1E2761")
        ax.set_ylabel(title)
    elif chart_type == "pie":
        ax.pie(values, labels=labels, autopct="%1.1f%%", colors=plt.cm.Blues(
            [0.9 - 0.5 * i / max(len(values) - 1, 1) for i in range(len(values))]
        ))
    else:  # bar
        ax.bar(labels, values, color="#1E2761")
        ax.set_ylabel(title)
    if chart_type != "pie":
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_title(title)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=120)
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def run_plot_tool(question: str, sql_output: Optional[SQLToolOutput] = None) -> PlotToolOutput:
    """
    Point d'entrée principal du PlotTool, appelé par MistralChat.py après le
    SQL Tool. `sql_output` doit être le résultat déjà obtenu pour la même
    question (évite un second appel SQL redondant) ; si absent, le PlotTool
    tente de l'obtenir lui-même (utile pour des tests/appels standalone).
    """
    with logfire.span("plot_tool", question=question):
        try:
            validated_input = PlotToolInput(question=question)
        except Exception as e:
            logger.warning(f"Question rejetée par PlotToolInput: {e}")
            return PlotToolOutput(error=f"Question invalide: {e}")

        if sql_output is None:
            from .sql_tool import run_sql_tool
            sql_output = run_sql_tool(validated_input.question)

        if sql_output.error:
            logger.info(f"PlotTool: pas de données exploitables ({sql_output.error})")
            return PlotToolOutput(error=f"Impossible de générer un graphique : {sql_output.error}")

        if sql_output.row_count == 0 or not sql_output.rows_preview:
            return PlotToolOutput(error="Impossible de générer un graphique : aucun résultat à représenter.")

        try:
            labels, values, value_col = _extract_labels_and_values(sql_output)
        except ValueError as e:
            logger.info(f"PlotTool: {e}")
            return PlotToolOutput(error=str(e))

        chart_type = _choose_chart_type(validated_input.question)
        title = value_col.replace("_", " ").capitalize()

        try:
            chart_base64 = _render_chart(chart_type, labels, values, title)
        except Exception as e:
            logger.error(f"Erreur lors du rendu du graphique: {e}")
            logfire.error("plot_render_error", error=str(e))
            return PlotToolOutput(error=f"Erreur lors du rendu du graphique: {e}")

        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        chart_path = PLOTS_DIR / f"plot_{abs(hash(question))}.png"
        try:
            chart_path.write_bytes(base64.b64decode(chart_base64))
        except Exception:
            chart_path = None  # non bloquant : le base64 suffit pour l'affichage Streamlit

        logfire.info("plot_tool_completed", chart_type=chart_type, question=question)
        return PlotToolOutput(
            chart_type=chart_type,
            chart_path=str(chart_path) if chart_path else None,
            chart_base64=chart_base64,
            title=title,
        )
