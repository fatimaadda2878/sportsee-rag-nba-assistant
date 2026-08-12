# utils/db.py
"""
Schéma relationnel (SQLAlchemy 2.0) — ALIGNÉ SUR LE VRAI FICHIER EXCEL.

Le fichier `regular_NBA.xlsx` fourni par Sarah contient des statistiques
AGRÉGÉES SUR LA SAISON (une ligne par joueur/passage en équipe), pas un log
match par match : pas de date, pas de home/away. Voir README.md section
"Limites des données sources" pour l'analyse complète de cet écart avec les
questions métier initialement envisagées ("5 derniers matchs", "domicile vs
extérieur").

Compatible SQLite (par défaut) et PostgreSQL (changement de SQL_DATABASE_URL
uniquement).

Tables :
    teams              -- référentiel équipes (code 3 lettres -> nom complet), feuille "Equipe"
    player_season_stats -- une ligne = un joueur pour un passage en équipe sur la saison, feuille "Données NBA"
    team_summary        -- résumé équipe fourni par le fichier source, feuille "Analyse"
    reports              -- rapports d'analyse texte (table prête, non alimentée par l'Excel actuel)

Voir docs/sql_examples.md pour des exemples de requêtes types.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import create_engine, ForeignKey, String, Integer, Float, Date, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import SQL_DATABASE_URL


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    team_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    team_name: Mapped[str] = mapped_column(String(80), nullable=False)

    def __repr__(self) -> str:
        return f"<Team {self.team_code} {self.team_name}>"


class PlayerSeasonStat(Base):
    __tablename__ = "player_season_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    team_code: Mapped[str] = mapped_column(ForeignKey("teams.team_code"), nullable=False, index=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # Cumuls saison (voir docstring module)
    pts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fgm: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fga: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fg_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    tpm: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tpa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tp_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ftm: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ft_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oreb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dreb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ast: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tov: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stl: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blk: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pf: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dd2: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    td3: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plus_minus: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Advanced stats
    off_rtg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    def_rtg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_rtg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ast_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ast_to: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ast_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oreb_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dreb_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reb_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    to_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    efg_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ts_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usg_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pace: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pie: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    poss: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    team: Mapped["Team"] = relationship()

    def __repr__(self) -> str:
        return f"<PlayerSeasonStat {self.player_name} ({self.team_code})>"


class TeamSummary(Base):
    """Résumé équipe tel que fourni directement par la feuille Excel "Analyse"
    (nombre de joueurs utilisés, total de points saison) — donnée déclarative,
    pas recalculée depuis player_season_stats, pour rester fidèle à la source."""
    __tablename__ = "team_summary"

    team_code: Mapped[str] = mapped_column(ForeignKey("teams.team_code"), primary_key=True)
    nb_players: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    team: Mapped["Team"] = relationship()

    def __repr__(self) -> str:
        return f"<TeamSummary {self.team_code} pts={self.total_points}>"


class Report(Base):
    """Table prête pour de futurs rapports texte (scouting, préparation...).
    Non alimentée par load_excel_to_db.py : aucune feuille "reports" dans le
    fichier source actuel."""
    __tablename__ = "reports"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_code: Mapped[Optional[str]] = mapped_column(String(3), nullable=True, index=True)
    player_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    report_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="autre")
    content: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<Report {self.report_id} ({self.category})>"


# ============================================================
# Engine / session helpers
# ============================================================

def get_engine(database_url: str = SQL_DATABASE_URL):
    """Crée l'engine SQLAlchemy. `future=True` pour l'API 2.0 stricte."""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=False, future=True, connect_args=connect_args)


def init_db(engine=None):
    """Crée les tables si elles n'existent pas encore (idempotent)."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(engine=None):
    engine = engine or init_db()
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
