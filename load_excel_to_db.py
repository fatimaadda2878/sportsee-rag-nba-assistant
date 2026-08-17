# load_excel_to_db.py
"""
Pipeline d'ingestion : Excel (regular_NBA.xlsx) -> validation Pydantic -> SQL.

Mapping VALIDÉ le 11/08/2026 avec Fatima sur le vrai fichier (feuilles,
colonnes, quelques lignes de données recoupées manuellement — FGM/FGA
correspondent bien à FG%, OREB+DREB=REB, etc.). Ce n'est plus une hypothèse.

Structure réelle du fichier (5 feuilles) :
    - "Données NBA" (570 lignes x 53 colonnes) : statistiques CUMULÉES SUR LA
      SAISON, une ligne par joueur/passage en équipe. Colonnes nommées 1..53
      (pas de texte), décodées via la feuille "Dictionnaire des données" et
      recoupement manuel des valeurs (voir COLUMN_ORDER ci-dessous). Colonnes
      46 à 53 : vides (NaN), ignorées. Une ligne d'en-tête textuelle dupliquée
      (valeurs "Player"/"Team"/"Age"...) traîne aussi dans les données elle-
      même : elle est rejetée automatiquement par la validation Pydantic
      (ge=16 sur l'âge, max_length=3 sur team_code), pas une anomalie à
      corriger.
    - "Equipe" (30 lignes) : code équipe (3 lettres) -> nom complet.
    - "Analyse" (130 lignes, header sur la ligne 5 du fichier soit index 4) :
      résumé équipe fourni directement par la source (nb joueurs utilisés,
      total de points saison). Sélection PAR POSITION (pas par nom de
      colonne) pour éviter tout souci d'apostrophe typographique/encodage
      sur "Nom complet de l'équipe".
    - "Analyse Vide" : même forme qu'"Analyse", non exploitée (doublon/gabarit
      vide constaté à l'inspection, ignorée par ce script).
    - Pas de feuille "reports" dans le fichier actuel : la table `reports`
      reste prête mais n'est pas peuplée par ce script.

⚠️ Limite majeure (voir README.md "Limites des données sources") : aucune
donnée par match ni de distinction domicile/extérieur n'existe dans ce
fichier. Les questions "% à 3 points sur les 5 derniers matchs" et
"comparaison domicile/extérieur" ne sont PAS répondables avec ces données —
le Tool SQL et l'agent sont conçus pour le signaler plutôt que d'halluciner
une réponse (voir utils/sql_tool.py).

Usage :
    python load_excel_to_db.py --excel-file data/regular_NBA.xlsx
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from utils.config import EXCEL_SOURCE_FILE
from utils.db import init_db, get_session_factory, Team, PlayerSeasonStat, TeamSummary

# ============================================================
# ⚠️ Bug corrigé le 17/08/2026 : `load_player_season_stats` utilisait
# `session.add(...)` (simple insertion, sans clé métier ni upsert) pour
# CHAQUE ligne, contrairement à `load_teams`/`load_team_summary` qui font
# `session.merge(...)` sur une clé primaire naturelle (team_code). Comme
# `PlayerSeasonStat.id` est un entier auto-incrémenté sans contrainte
# d'unicité métier, relancer ce script plusieurs fois empilait les lignes
# à l'infini au lieu de les remplacer : la base contenait 1707 lignes dans
# `player_season_stats` pour 569 joueurs réels dans le fichier source
# (exactement x3, confirmant 3 exécutions successives du script sans purge
# préalable). Cette duplication expliquait notamment un classement "top 3
# passeurs" renvoyant 3 fois le même joueur (voir Rapport_Evaluation_RAG.md,
# section 4.2, cas T10). Corrigé ci-dessous en vidant la table avant
# réinsertion (rechargement complet à chaque exécution).
# ============================================================
from utils.schemas import TeamRow, PlayerSeasonStatRow, TeamSummaryRow
from utils.observability import logfire

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("load_excel_to_db")


# ============================================================
# Mapping position -> champ, feuille "Données NBA" (colonnes 1 à 45)
# Validé par recoupement des totaux (FGM/FGA=FG%, OREB+DREB=REB, etc.)
# ============================================================
COLUMN_ORDER = [
    "player_name", "team_code", "age", "games_played", "wins", "losses", "min_avg",
    "pts_total", "fgm", "fga", "fg_pct", "tpm", "tpa", "tp_pct", "ftm", "fta", "ft_pct",
    "oreb", "dreb", "reb", "ast", "tov", "stl", "blk", "pf", "fp", "dd2", "td3",
    "plus_minus", "off_rtg", "def_rtg", "net_rtg", "ast_pct", "ast_to", "ast_ratio",
    "oreb_pct", "dreb_pct", "reb_pct", "to_ratio", "efg_pct", "ts_pct", "usg_pct",
    "pace", "pie", "poss",
]
assert len(COLUMN_ORDER) == 45

# Feuille "Analyse", ligne d'en-tête réelle = index 4. Ordre des colonnes
# (position, pas nom littéral - plus robuste face aux apostrophes typo/encodage) :
# 0=Code, 1=Nom complet de l'équipe, 2=Nombre de joueur par équipe, 3=Nombre de point total par équipe
ANALYSE_COLUMN_ORDER = ["team_code", "team_name", "nb_players", "total_points"]


def _validate_rows(records: list[dict], model) -> tuple[list, int]:
    valid_rows = []
    errors = 0
    for record in records:
        try:
            valid_rows.append(model(**record))
        except ValidationError as e:
            errors += 1
            logger.warning(f"Ligne rejetée par validation Pydantic ({model.__name__}): {e.errors()[:2]}")
    return valid_rows, errors


def load_teams(excel_file: pd.ExcelFile, session) -> int:
    if "Equipe" not in excel_file.sheet_names:
        logger.warning("Feuille 'Equipe' non trouvée, étape ignorée.")
        return 0
    df = excel_file.parse("Equipe")
    # Sélection par position (2 premières colonnes) : robuste face aux
    # variations d'apostrophe/encodage sur les noms de colonnes.
    df = df.iloc[:, :2]
    df.columns = ["team_code", "team_name"]
    df = df.dropna(subset=["team_code"])

    valid_rows, errors = _validate_rows(df.to_dict(orient="records"), TeamRow)
    for row in valid_rows:
        session.merge(Team(team_code=row.team_code, team_name=row.team_name))
    session.commit()
    logfire.info("excel_ingestion_teams", nb_valid=len(valid_rows), nb_errors=errors)
    logger.info(f"teams: {len(valid_rows)} lignes insérées, {errors} rejetées.")
    return len(valid_rows)


def load_player_season_stats(excel_file: pd.ExcelFile, session) -> int:
    sheet_name = "Données NBA"
    if sheet_name not in excel_file.sheet_names:
        logger.error(f"Feuille '{sheet_name}' non trouvée. Ingestion des stats impossible.")
        return 0

    df = excel_file.parse(sheet_name)
    # Les colonnes réelles sont numérotées 1..53 (pas de texte) : on ne garde
    # que les 45 premières, dans l'ordre validé, et on ignore 46-53 (vides).
    nb_cols = len(COLUMN_ORDER)
    df = df.iloc[:, :nb_cols]
    df.columns = COLUMN_ORDER
    df = df.dropna(subset=["player_name", "team_code"])

    valid_rows, errors = _validate_rows(df.to_dict(orient="records"), PlayerSeasonStatRow)

    # Purge avant réinsertion : pas de clé métier naturelle sur cette table
    # (id auto-incrémenté), donc un simple `add()` dupliquerait les lignes à
    # chaque exécution du script (voir note en tête de fichier).
    nb_deleted = session.query(PlayerSeasonStat).delete()
    if nb_deleted:
        logger.info(f"player_season_stats: {nb_deleted} lignes existantes purgées avant réinsertion.")

    for row in valid_rows:
        session.add(PlayerSeasonStat(**row.model_dump()))
    session.commit()
    logfire.info("excel_ingestion_player_season_stats", nb_valid=len(valid_rows), nb_errors=errors)
    logger.info(f"player_season_stats: {len(valid_rows)} lignes insérées, {errors} rejetées.")
    return len(valid_rows)


def load_team_summary(excel_file: pd.ExcelFile, session) -> int:
    if "Analyse" not in excel_file.sheet_names:
        logger.warning("Feuille 'Analyse' non trouvée, étape ignorée.")
        return 0
    # Le vrai en-tête est sur la ligne 5 du fichier Excel (index 4), les 4
    # lignes précédentes sont vides dans la feuille source.
    df = excel_file.parse("Analyse", header=4)
    # Sélection par POSITION (pas par nom de colonne) : "Nom complet de
    # l'équipe" contient une apostrophe qui peut différer d'un encodage à
    # l'autre (apostrophe droite vs typographique) et faisait échouer le
    # rename par nom. Les 4 premières colonnes sont, dans l'ordre :
    # Code, Nom complet de l'équipe, Nombre de joueur par équipe, Nombre de point total par équipe.
    df = df.iloc[:, :len(ANALYSE_COLUMN_ORDER)]
    df.columns = ANALYSE_COLUMN_ORDER
    df = df.dropna(subset=["team_code"])

    valid_rows, errors = _validate_rows(df.to_dict(orient="records"), TeamSummaryRow)
    for row in valid_rows:
        session.merge(TeamSummary(
            team_code=row.team_code, nb_players=row.nb_players, total_points=row.total_points
        ))
    session.commit()
    logfire.info("excel_ingestion_team_summary", nb_valid=len(valid_rows), nb_errors=errors)
    logger.info(f"team_summary: {len(valid_rows)} lignes insérées, {errors} rejetées.")
    return len(valid_rows)


def run(excel_path: str) -> None:
    path = Path(excel_path)
    if not path.exists():
        logger.error(f"Fichier Excel introuvable: {excel_path}")
        sys.exit(1)

    with logfire.span("load_excel_to_db", excel_file=str(path)):
        engine = init_db()
        Session = get_session_factory(engine)
        session = Session()

        excel_file = pd.ExcelFile(path)
        logger.info(f"Feuilles détectées dans {path.name}: {excel_file.sheet_names}")

        totals = {
            "teams": load_teams(excel_file, session),
            "player_season_stats": load_player_season_stats(excel_file, session),
            "team_summary": load_team_summary(excel_file, session),
        }
        session.close()

        logger.info(f"Ingestion terminée: {totals}")
        logfire.info("excel_ingestion_completed", **totals)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingestion Excel -> base SQL (teams/player_season_stats/team_summary)")
    parser.add_argument("--excel-file", type=str, default=EXCEL_SOURCE_FILE,
                         help=f"Chemin du fichier Excel source (par défaut: {EXCEL_SOURCE_FILE})")
    args = parser.parse_args()
    run(args.excel_file)
