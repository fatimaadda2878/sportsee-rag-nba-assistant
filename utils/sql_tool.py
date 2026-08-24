# utils/sql_tool.py
"""
Tool SQL : traduit une question en langage naturel en requête SQL (few-shot),
l'exécute sur la base teams/player_season_stats/team_summary, et retourne un
résultat structuré (validé par SQLToolOutput) que l'agent peut ensuite
synthétiser.

Génération NL -> SQL via LangChain (`create_sql_query_chain` + `SQLDatabase`
+ `ChatMistralAI`), conformément aux consignes du projet (retour de relecture
de Sylvain, mentor, le 23/08/2026 : "le projet demande d'utiliser LangChain
et d'utiliser un SQL Tool LangChain"). Un fallback vers l'appel direct au SDK
Mistral (`generate_sql_direct_mistral`, l'implémentation d'origine) est
conservé si l'initialisation de la chaîne LangChain échoue (import, DB
injoignable...) — même philosophie de dégradation gracieuse que le routeur
heuristique et le fallback OCR.

Sécurité : quelle que soit la méthode de génération (LangChain ou fallback),
on n'exécute JAMAIS la requête générée par le LLM telle quelle sans
garde-fous — ceux-ci sont appliqués en post-traitement, après génération et
avant toute exécution :
    - uniquement des requêtes SELECT (rejet de tout DML/DDL)
    - LIMIT forcé à SQL_TOOL_MAX_ROWS
    - la question d'entrée est validée par SQLToolInput (anti-injection basique)
    - détection explicite des questions hors périmètre des données (voir
      mécanisme NO_DATA ci-dessous)
    - rejet des valeurs (noms de joueurs/équipes) halluciné(e)s absentes de
      la question d'origine (_uses_only_values_from_question)

Ce choix de conception (LangChain uniquement pour la GÉNÉRATION de la
requête, jamais pour son EXÉCUTION) est délibéré : `create_sql_query_chain`
renvoie une chaîne SQL sans l'exécuter, contrairement à `create_sql_agent`
qui exécute lui-même la requête dans sa propre boucle d'agent — ce qui
rendrait l'injection de nos garde-fous entre génération et exécution
beaucoup plus difficile (voir Rapport_Evaluation_RAG.md).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import MODEL_NAME, SQL_TOOL_MAX_ROWS, MISTRAL_API_KEY
from .db import get_engine
from .schemas import SQLToolInput, SQLToolOutput
from .observability import logfire
from .mistral_client import chat_complete, MistralClientError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sql_tool")


# ============================================================
# Description du schéma (injectée dans le prompt)
#
# ⚠️ IMPORTANT : la base contient des statistiques AGRÉGÉES SUR LA SAISON
# (une ligne par joueur), PAS un log match par match. Il n'y a NI colonne
# date, NI distinction domicile/extérieur nulle part. Voir README.md
# "Limites des données sources". Le prompt ci-dessous instruit donc
# explicitement le LLM à répondre "NO_DATA" plutôt que d'halluciner une
# requête sur des données qui n'existent pas (ex: "5 derniers matchs",
# "à domicile vs à l'extérieur").
# ============================================================
SCHEMA_DESCRIPTION = """
Table teams(team_code TEXT(3) PK, team_name TEXT)

Table player_season_stats(id INTEGER PK, player_name TEXT, team_code TEXT FK->teams,
    age INTEGER, games_played INTEGER, wins INTEGER, losses INTEGER, min_avg REAL,
    pts_total INTEGER (total de points SUR LA SAISON, pas une moyenne),
    fgm INTEGER, fga INTEGER, fg_pct REAL,
    tpm INTEGER (3-points réussis, total saison), tpa INTEGER (3-points tentés, total saison), tp_pct REAL,
    ftm INTEGER, fta INTEGER, ft_pct REAL,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, tov INTEGER, stl INTEGER, blk INTEGER, pf INTEGER,
    fp REAL, dd2 INTEGER, td3 INTEGER, plus_minus REAL,
    off_rtg REAL, def_rtg REAL, net_rtg REAL, ast_pct REAL, ast_to REAL, ast_ratio REAL,
    oreb_pct REAL, dreb_pct REAL, reb_pct REAL, to_ratio REAL, efg_pct REAL, ts_pct REAL, usg_pct REAL,
    pace REAL, pie REAL, poss INTEGER)
-- Une ligne = un joueur pour un passage dans une équipe sur TOUTE la saison
-- régulière (pas un match). Un joueur transféré en cours de saison a
-- plusieurs lignes (une par équipe). Pour une moyenne par match, diviser un
-- total par games_played (ex: pts_total * 1.0 / games_played).

Table team_summary(team_code TEXT PK FK->teams, nb_players INTEGER, total_points INTEGER)
-- Résumé équipe fourni directement par la source (total de points saison).

Table reports(report_id INTEGER PK, team_code TEXT NULL, player_name TEXT NULL,
              report_date DATE, author TEXT, category TEXT, content TEXT)
-- Table prête pour de futurs rapports texte, actuellement VIDE (aucune
-- donnée de rapport dans le fichier source actuel).

DONNÉES ABSENTES DE CETTE BASE (ne jamais inventer une requête dessus) :
- Aucune date de match, aucune notion de "match" individuel -> impossible de
  répondre à "sur les N derniers matchs" ou "lors du dernier match".
- Aucune colonne domicile/extérieur -> impossible de comparer "à domicile"
  vs "à l'extérieur".
"""

# ============================================================
# Exemples few-shot (NL -> SQL). Voir docs/sql_examples.md pour plus de cas.
# ============================================================
FEW_SHOT_EXAMPLES = """
Q: Quel joueur a le meilleur pourcentage de réussite à 3 points cette saison (minimum 50 tentatives) ?
SQL:
SELECT player_name, team_code, tpm, tpa, tp_pct
FROM player_season_stats
WHERE tpa >= 50
ORDER BY tp_pct DESC
LIMIT 10;

Q: Quel joueur a le meilleur pourcentage de réussite à 3 points sur les 5 derniers matchs ?
SQL:
NO_DATA: aucune donnée par match n'existe dans cette base (statistiques agrégées sur la saison entière uniquement).

Q: Compare les statistiques de rebonds de l'équipe à domicile et à l'extérieur.
SQL:
NO_DATA: aucune colonne domicile/extérieur n'existe dans cette base (statistiques agrégées sur la saison entière uniquement).

Q: Quels sont les 5 meilleurs marqueurs par match cette saison ?
SQL:
SELECT player_name, team_code,
       ROUND(pts_total * 1.0 / NULLIF(games_played, 0), 1) AS pts_per_game
FROM player_season_stats
WHERE games_played > 0
ORDER BY pts_per_game DESC
LIMIT 5;

Q: Quelle équipe a marqué le plus de points au total cette saison ?
SQL:
SELECT ts.team_code, t.team_name, ts.total_points
FROM team_summary ts
JOIN teams t ON t.team_code = ts.team_code
ORDER BY ts.total_points DESC
LIMIT 5;

Q: Quels sont les 3 meilleurs passeurs en moyenne par match ?
SQL:
SELECT player_name, team_code,
       ROUND(ast * 1.0 / NULLIF(games_played, 0), 1) AS ast_per_game
FROM player_season_stats
WHERE games_played >= 10
ORDER BY ast_per_game DESC
LIMIT 3;
"""

SQL_GENERATION_PROMPT = """Tu es un générateur de requêtes SQL (dialecte SQLite) pour une base de données de statistiques NBA agrégées sur la saison.

Schéma de la base :
{schema}

Exemples de questions et requêtes correspondantes :
{few_shot}

Règles strictes :
- Réponds UNIQUEMENT avec la requête SQL, sans texte autour, sans balises markdown.
- Une seule instruction SELECT (jamais INSERT/UPDATE/DELETE/DROP/ALTER).
- Utilise toujours des JOIN explicites avec des alias clairs.
- Ajoute une clause LIMIT raisonnable si la question ne précise pas de borne.
- Si la question porte sur une donnée absente de la base (match par match,
  date précise, domicile/extérieur), réponds EXACTEMENT au format
  "NO_DATA: <raison courte>" au lieu d'une requête SQL. Ne tente jamais
  d'approximer avec une autre colonne.

Question : {question}
SQL:"""

# ============================================================
# Prompt LangChain (utilisé par `create_sql_query_chain`, voie principale de
# génération SQL — voir docstring du module).
#
# `create_sql_query_chain` exige un PromptTemplate exposant précisément les
# variables 'input', 'top_k', 'table_info' (+ 'dialect' optionnelle, qu'il
# renseigne alors automatiquement avec `db.dialect`). Le texte du few-shot et
# des règles métier (NO_DATA, cumuls saison vs moyenne/match...) est injecté
# ici en dur (pas comme variable de template) pour rester strictement
# identique à la voie de secours `generate_sql_direct_mistral`.
# `table_info` est fourni dynamiquement par LangChain (introspection réelle
# de la base via SQLAlchemy, colonnes + quelques lignes d'exemple) plutôt que
# par la description statique SCHEMA_DESCRIPTION ci-dessus, qui reste
# utilisée uniquement par la voie de secours.
# ============================================================
_LANGCHAIN_SQL_TEMPLATE = (
    "Tu es un générateur de requêtes SQL (dialecte {dialect}) pour une base "
    "de données de statistiques NBA agrégées sur la saison.\n\n"
    "Tables disponibles (colonnes et exemples de lignes) :\n{table_info}\n\n"
    "Notes importantes sur les données :\n"
    "- pts_total, tpm, tpa, ast, reb, etc. sont des CUMULS SUR LA SAISON, pas "
    "des moyennes par match. Pour une moyenne par match, diviser par "
    "games_played (ex: pts_total * 1.0 / NULLIF(games_played, 0)).\n"
    "- Aucune date de match, aucune notion de match individuel n'existe dans "
    "cette base : impossible de répondre à \"sur les N derniers matchs\" ou "
    "\"lors du dernier match\".\n"
    "- Aucune colonne domicile/extérieur n'existe : impossible de comparer "
    "\"à domicile\" vs \"à l'extérieur\".\n"
    "- Si la question porte sur une donnée absente de la base (match par "
    "match, date précise, domicile/extérieur), réponds EXACTEMENT au format "
    "\"NO_DATA: <raison courte>\" au lieu d'une requête SQL. Ne tente jamais "
    "d'approximer avec une autre colonne.\n\n"
    "Exemples de questions et requêtes correspondantes :\n"
    f"{FEW_SHOT_EXAMPLES}\n\n"
    "Règles strictes :\n"
    "- Réponds UNIQUEMENT avec la requête SQL, sans texte autour, sans "
    "balises markdown.\n"
    "- Une seule instruction SELECT (jamais INSERT/UPDATE/DELETE/DROP/ALTER).\n"
    "- Utilise toujours des JOIN explicites avec des alias clairs.\n"
    "- Limite le résultat à environ {top_k} lignes si la question ne "
    "précise pas de borne.\n\n"
    "{input}"
)


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|PRAGMA|REPLACE)\b", re.IGNORECASE
)


def _clean_generated_sql(raw_sql: str) -> str:
    """Nettoie la sortie LLM (retire ```sql ... ``` éventuels)."""
    cleaned = raw_sql.strip()
    cleaned = re.sub(r"^```(sql)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    if cleaned.upper().startswith("NO_DATA"):
        return cleaned  # pas de SQL à formater : le LLM signale une donnée absente
    if not cleaned.endswith(";"):
        cleaned += ";"
    return cleaned


def _is_safe_select(sql: str) -> bool:
    if not sql.strip().upper().startswith("SELECT"):
        return False
    if _FORBIDDEN_KEYWORDS.search(sql):
        return False
    if ";" in sql.strip()[:-1]:  # plusieurs instructions empilées
        return False
    return True


def _enforce_limit(sql: str, max_rows: int = SQL_TOOL_MAX_ROWS) -> str:
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    return sql.rstrip(";") + f" LIMIT {max_rows};"


_STRING_LITERAL_PATTERN = re.compile(r"'([^']*)'")


def _uses_only_values_from_question(sql: str, question: str) -> bool:
    """Garde-fou anti-hallucination de valeur (corrigé le 17/08/2026).

    Cas détecté lors de l'évaluation RAGAS (cas de test T06) : pour la
    question "Combien de points au total un joueur donné a-t-il marqués
    cette saison régulière ?" (aucun joueur nommé), le générateur SQL
    produisait de sa propre initiative `WHERE player_name = 'LeBron James'`
    au lieu de répondre NO_DATA ou de signaler l'ambiguïté.

    Ici, on rejette toute requête dont un littéral texte (nom de joueur,
    équipe...) n'a aucun mot en commun avec la question d'origine. On
    vérifie mot par mot (pas le littéral entier) pour ne pas rejeter à
    tort une résolution partielle légitime (ex: question mentionnant
    "Lebron" -> SQL généré avec 'LeBron James').
    """
    question_lower = question.lower()
    for literal in _STRING_LITERAL_PATTERN.findall(sql):
        words = [w for w in re.findall(r"[a-zA-ZÀ-ÿ]+", literal.strip()) if len(w) > 2]
        if words and not any(w.lower() in question_lower for w in words):
            return False
    return True


# ============================================================
# Chaîne LangChain (voie principale de génération SQL)
# ============================================================
# Tables exposées au LLM via LangChain (on n'inclut pas `reports`, table
# prête mais actuellement vide/non alimentée — inutile de la faire figurer
# dans le schéma soumis au LLM, cf. `SCHEMA_DESCRIPTION` qui explique déjà
# le choix pour la voie de secours).
_LANGCHAIN_TABLES = ["teams", "player_season_stats", "team_summary"]

_sql_chain = None  # singleton paresseux (même style que router._get_router_agent)


def _get_sql_chain():
    """Construit (une seule fois) la chaîne LangChain `create_sql_query_chain`.

    Réutilise l'engine SQLAlchemy déjà configuré par `utils.db.get_engine`
    (donc le SQL_DATABASE_URL actif, PostgreSQL par défaut ou SQLite en
    dépannage — voir utils/config.py) : LangChain n'ouvre pas sa propre
    connexion séparée.
    """
    global _sql_chain
    if _sql_chain is None:
        # Imports différés : ces dépendances (LangChain + langchain-mistralai)
        # ne sont nécessaires qu'ici, pas au chargement du module (cohérent
        # avec le reste du projet — voir evaluate_ragas.py pour ragas/langchain).
        from langchain.chains import create_sql_query_chain
        from langchain_community.utilities import SQLDatabase
        from langchain_core.prompts import PromptTemplate
        from langchain_mistralai import ChatMistralAI

        db = SQLDatabase(get_engine(), include_tables=_LANGCHAIN_TABLES, sample_rows_in_table_info=2)
        llm = ChatMistralAI(model=MODEL_NAME, mistral_api_key=MISTRAL_API_KEY, temperature=0.0)
        prompt = PromptTemplate.from_template(_LANGCHAIN_SQL_TEMPLATE)
        _sql_chain = create_sql_query_chain(llm, db, prompt=prompt, k=SQL_TOOL_MAX_ROWS)
    return _sql_chain


def generate_sql_langchain(question: str) -> str:
    """Génère la requête SQL via la chaîne LangChain `create_sql_query_chain`
    (voie principale — voir docstring du module). Ne génère QUE la requête,
    ne l'exécute jamais (l'exécution + les garde-fous restent gérés par
    `run_sql_tool`, hors LangChain)."""
    chain = _get_sql_chain()
    raw_sql = chain.invoke({"question": question})
    return _clean_generated_sql(raw_sql)


def generate_sql_direct_mistral(question: str) -> str:
    """Génère la requête SQL par appel direct au SDK Mistral (implémentation
    d'origine, conservée comme repli si la chaîne LangChain échoue à
    s'initialiser ou à répondre — voir docstring du module)."""
    prompt = SQL_GENERATION_PROMPT.format(
        schema=SCHEMA_DESCRIPTION, few_shot=FEW_SHOT_EXAMPLES, question=question
    )
    raw_sql = chat_complete(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return _clean_generated_sql(raw_sql)


def generate_sql(question: str) -> str:
    """Point d'entrée génération SQL : LangChain en priorité, repli
    automatique sur l'appel direct Mistral en cas d'échec (import,
    connexion DB, erreur LLM...) — jamais d'exception qui remonte."""
    try:
        sql = generate_sql_langchain(question)
        logfire.info("sql_generation_method", method="langchain")
        return sql
    except Exception as e:
        logger.warning(f"Génération SQL via LangChain indisponible, repli sur l'appel direct Mistral: {e}")
        logfire.info("sql_generation_method", method="direct_mistral_fallback", langchain_error=str(e))
        return generate_sql_direct_mistral(question)


def run_sql_tool(question: str) -> SQLToolOutput:
    """
    Point d'entrée principal du SQL Tool, appelé par l'agent (MistralChat.py).
    Valide l'entrée, génère la requête, l'exécute avec garde-fous, et retourne
    un SQLToolOutput structuré (jamais d'exception qui remonte jusqu'à l'UI).
    """
    with logfire.span("sql_tool", question=question):
        try:
            validated_input = SQLToolInput(question=question)
        except Exception as e:
            logger.warning(f"Question rejetée par SQLToolInput: {e}")
            return SQLToolOutput(generated_sql="", row_count=0, error=f"Question invalide: {e}")

        try:
            generated_sql = generate_sql(validated_input.question)
        except Exception as e:
            logger.error(f"Erreur lors de la génération SQL: {e}")
            logfire.error("sql_generation_error", error=str(e))
            return SQLToolOutput(generated_sql="", row_count=0, error=f"Erreur génération SQL: {e}")

        if generated_sql.upper().startswith("NO_DATA"):
            reason = generated_sql.split(":", 1)[1].strip() if ":" in generated_sql else generated_sql
            logger.info(f"Question hors du périmètre des données disponibles: {reason}")
            logfire.info("sql_tool_no_data", question=question, reason=reason)
            return SQLToolOutput(
                generated_sql="", row_count=0,
                error=f"Donnée non disponible dans la base actuelle : {reason}",
            )

        if not _is_safe_select(generated_sql):
            logger.warning(f"Requête générée rejetée (non-SELECT ou motif interdit): {generated_sql}")
            logfire.info("sql_generation_rejected", sql=generated_sql)
            return SQLToolOutput(
                generated_sql=generated_sql, row_count=0,
                error="Requête générée rejetée par les garde-fous de sécurité (SELECT uniquement)."
            )

        if not _uses_only_values_from_question(generated_sql, validated_input.question):
            logger.warning(f"Requête générée rejetée (valeur absente de la question): {generated_sql}")
            logfire.info("sql_generation_value_not_in_question", sql=generated_sql, question=question)
            return SQLToolOutput(
                generated_sql=generated_sql, row_count=0,
                error=(
                    "Requête générée rejetée : elle référence une valeur (ex. nom de joueur/équipe) "
                    "absente de la question posée. Merci de préciser la question."
                ),
            )

        safe_sql = _enforce_limit(generated_sql)

        try:
            engine = get_engine()
            with engine.connect() as conn:
                result = conn.execute(text(safe_sql))
                columns = list(result.keys())
                rows = [dict(zip(columns, row)) for row in result.fetchall()]
        except SQLAlchemyError as e:
            logger.error(f"Erreur d'exécution SQL: {e}")
            logfire.error("sql_execution_error", sql=safe_sql, error=str(e))
            return SQLToolOutput(generated_sql=safe_sql, row_count=0, error=f"Erreur d'exécution SQL: {e}")

        truncated = len(rows) >= SQL_TOOL_MAX_ROWS
        output = SQLToolOutput(
            generated_sql=safe_sql,
            row_count=len(rows),
            truncated=truncated,
            columns=columns,
            rows_preview=rows[:20],  # aperçu limité pour le prompt LLM / les logs
        )
        logfire.info("sql_tool_completed", sql=safe_sql, row_count=len(rows))
        return output
