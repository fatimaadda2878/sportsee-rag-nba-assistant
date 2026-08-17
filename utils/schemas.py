# utils/schemas.py
"""
Modèles Pydantic utilisés pour sécuriser les flux d'entrée/sortie de la chaîne
RAG + SQL :

1. Pipeline de préparation des données (chunking / embedding)      -> DocumentChunk
2. Ingestion Excel -> base de données (Étape 2)                     -> TeamRow, PlayerSeasonStatRow, TeamSummaryRow, ReportRow
3. Tool SQL (entrée = question utilisateur, sortie = résultat SQL)  -> SQLToolInput, SQLToolOutput
4. Jeu de tests d'évaluation RAGAS (Étape 1 & 3)                    -> EvalTestCase

⚠️ Schéma Excel réel (validé le 11/08/2026 avec Fatima) : le fichier
`regular_NBA.xlsx` contient des STATISTIQUES AGRÉGÉES SUR LA SAISON (une
ligne par joueur, feuille "Données NBA", 570 lignes x 53 colonnes dont 45
utiles), PAS un log match par match. Aucune colonne date, aucun découpage
domicile/extérieur. Voir README.md section "Limites des données sources"
pour l'analyse complète de cet impact sur les questions métier.

Ces modèles sont volontairement stricts (types, bornes, formats) : toute
donnée qui ne les respecte pas est rejetée avant d'entrer dans le pipeline,
ce qui évite de propager des erreurs silencieuses jusqu'au LLM.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator, ConfigDict


# ============================================================
# 1. Pipeline RAG texte (chunking / embedding)
# ============================================================

class ChunkMetadata(BaseModel):
    """Métadonnées attachées à chaque chunk indexé dans Faiss."""
    model_config = ConfigDict(extra="allow")  # tolère les clés additionnelles (filename, category, etc.)

    source: str = Field(..., min_length=1, description="Chemin relatif du document source")
    filename: str = Field(..., min_length=1)
    category: str = Field(default="root")
    chunk_id_in_doc: int = Field(..., ge=0)
    start_index: int = Field(default=-1)
    full_path: Optional[str] = None
    sheet: Optional[str] = None


class DocumentChunk(BaseModel):
    """Un chunk de texte prêt à être embeddé et indexé."""
    id: str = Field(..., pattern=r"^\d+_\d+$", description="Format doc_index_chunk_index, ex: '3_12'")
    text: str = Field(..., min_length=1, max_length=8000)
    metadata: ChunkMetadata

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Le texte du chunk est vide après nettoyage.")
        return v.strip()


# ============================================================
# 2. Ingestion Excel -> DB (Étape 2)
# ============================================================

class TeamRow(BaseModel):
    """Une ligne validée de la table `teams` (feuille Excel "Equipe")."""
    team_code: str = Field(..., min_length=2, max_length=3)
    team_name: str = Field(..., min_length=1)

    @field_validator("team_code")
    @classmethod
    def upper_code(cls, v: str) -> str:
        return v.strip().upper()


class PlayerSeasonStatRow(BaseModel):
    """
    Une ligne validée de la table `player_season_stats` (feuille Excel
    "Données NBA"). Une ligne = un joueur pour un passage dans une équipe sur
    la saison (un joueur transféré en cours de saison peut apparaître
    plusieurs fois, une fois par équipe).

    Les totaux (pts_total, fgm, fga, ftm, fta, oreb, dreb, reb, ast, tov,
    stl, blk, pf, fp, poss) sont des CUMULS SAISON, pas des moyennes par
    match (contrairement à ce qu'indique la feuille "Dictionnaire des
    données" pour PTS, imprécision confirmée par recoupement FGM/FGA=FG%).
    """
    player_name: str = Field(..., min_length=1)
    team_code: str = Field(..., min_length=2, max_length=3)
    age: int = Field(..., ge=16, le=50)
    games_played: int = Field(..., ge=0, le=90)
    wins: int = Field(..., ge=0)
    losses: int = Field(..., ge=0)
    min_avg: float = Field(..., ge=0, le=48)
    pts_total: int = Field(..., ge=0)
    fgm: int = Field(..., ge=0)
    fga: int = Field(..., ge=0)
    fg_pct: float = Field(..., ge=0, le=100)
    tpm: int = Field(default=0, ge=0, description="3PM saison (colonne corrompue en '15:00:00' dans le fichier source)")
    tpa: int = Field(default=0, ge=0)
    tp_pct: Optional[float] = Field(default=None, ge=0, le=100)
    ftm: int = Field(default=0, ge=0)
    fta: int = Field(default=0, ge=0)
    ft_pct: Optional[float] = Field(default=None, ge=0, le=100)
    oreb: int = Field(default=0, ge=0)
    dreb: int = Field(default=0, ge=0)
    reb: int = Field(default=0, ge=0)
    ast: int = Field(default=0, ge=0)
    tov: int = Field(default=0, ge=0)
    stl: int = Field(default=0, ge=0)
    blk: int = Field(default=0, ge=0)
    pf: int = Field(default=0, ge=0)
    fp: Optional[float] = None
    dd2: int = Field(default=0, ge=0)
    td3: int = Field(default=0, ge=0)
    plus_minus: Optional[float] = None
    off_rtg: Optional[float] = None
    def_rtg: Optional[float] = None
    net_rtg: Optional[float] = None
    ast_pct: Optional[float] = None
    ast_to: Optional[float] = None
    ast_ratio: Optional[float] = None
    oreb_pct: Optional[float] = None
    dreb_pct: Optional[float] = None
    reb_pct: Optional[float] = None
    to_ratio: Optional[float] = None
    efg_pct: Optional[float] = None
    ts_pct: Optional[float] = None
    usg_pct: Optional[float] = None
    pace: Optional[float] = None
    pie: Optional[float] = None
    poss: Optional[int] = Field(default=None, ge=0)

    @field_validator("player_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("player_name vide non autorisé.")
        return v

    @field_validator("team_code")
    @classmethod
    def upper_team_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("fga")
    @classmethod
    def fga_geq_fgm(cls, v, info):
        # NB : le validator doit être posé sur `fga` (et lire `fgm` déjà
        # validé via info.data), pas l'inverse : en Pydantic v2, un
        # field_validator ne voit dans info.data que les champs déjà
        # validés, c'est-à-dire ceux déclarés AVANT lui dans la classe.
        # `fgm` est déclaré avant `fga` ci-dessus, donc c'est bien
        # accessible ici (l'inverse ne fonctionnerait pas : un validator
        # sur `fgm` ne verrait jamais `fga`, qui est déclaré après).
        fgm = info.data.get("fgm")
        if fgm is not None and fgm > v:
            raise ValueError("fgm ne peut pas dépasser fga.")
        return v


class TeamSummaryRow(BaseModel):
    """
    Une ligne validée de la table `team_summary` (feuille Excel "Analyse"),
    un résumé équipe fourni directement dans le fichier source (nombre de
    joueurs utilisés, total de points de la saison).
    """
    team_code: str = Field(..., min_length=2, max_length=3)
    team_name: str = Field(..., min_length=1)
    nb_players: int = Field(..., ge=0)
    total_points: int = Field(..., ge=0)

    @field_validator("team_code")
    @classmethod
    def upper_code(cls, v: str) -> str:
        return v.strip().upper()


class ReportRow(BaseModel):
    """
    Une ligne validée de la table `reports` (rapport d'analyse texte).
    Aucune feuille "reports" n'existe dans le fichier Excel actuel : cette
    table reste prête pour de futurs rapports (scouting, préparation...)
    ajoutés manuellement ou par un autre flux, non alimentée par
    load_excel_to_db.py pour l'instant.
    """
    report_id: int = Field(..., ge=1)
    team_code: Optional[str] = Field(default=None, min_length=2, max_length=3)
    player_name: Optional[str] = None
    report_date: dt.date
    author: Optional[str] = None
    category: Literal["preparation", "post_match", "scouting", "medical", "autre"] = "autre"
    content: str = Field(..., min_length=1)


# ============================================================
# 3. Tool SQL (few-shot NL -> SQL)
# ============================================================

class SQLToolInput(BaseModel):
    """Entrée du SQL Tool : la question utilisateur en langage naturel."""
    question: str = Field(..., min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def no_sql_injection_markers(cls, v: str) -> str:
        forbidden = [";--", "/*", "*/", "xp_cmdshell"]
        lowered = v.lower()
        if any(tok in lowered for tok in forbidden):
            raise ValueError("Question rejetée : motif potentiellement dangereux détecté.")
        return v


class SQLToolOutput(BaseModel):
    """Sortie du SQL Tool : requête générée + résultat, pour traçabilité (Logfire)."""
    generated_sql: str
    row_count: int = Field(..., ge=0)
    truncated: bool = False
    columns: list[str] = Field(default_factory=list)
    rows_preview: list[dict] = Field(default_factory=list, description="Aperçu limité des lignes (garde-fou taille)")
    error: Optional[str] = None


# ============================================================
# 4. Jeu de tests d'évaluation (RAGAS)
# ============================================================

class TestCategory(str, Enum):
    SIMPLE_TEXTE = "simple_texte"
    COMPLEXE_TEXTE = "complexe_texte"
    BRUITE_TEXTE = "bruite_texte"
    SIMPLE_CHIFFRE = "simple_chiffre"
    COMPLEXE_CHIFFRE = "complexe_chiffre"
    MIXTE_TEXTE_CHIFFRE = "mixte_texte_chiffre"
    HORS_PERIMETRE = "hors_perimetre"


class EvalTestCase(BaseModel):
    """Un cas de test métier utilisé par evaluate_ragas.py."""
    id: str
    category: TestCategory
    question: str = Field(..., min_length=3)
    ground_truth: str = Field(..., min_length=1, description="Réponse de référence attendue")
    requires_sql: bool = Field(default=False, description="True si la question nécessite le SQL Tool")
    notes: Optional[str] = None
