# Exemples de requêtes SQL types

Ce document sert de référence pour comprendre le schéma réel de la base
(validé le 11/08/2026 sur le fichier `regular_NBA.xlsx` fourni par Sarah) et
pour enrichir les exemples few-shot du SQL Tool (`utils/sql_tool.py`).

## ⚠️ Nature réelle des données — à lire avant tout

Le fichier source contient des **statistiques agrégées sur la saison
régulière complète**, une ligne par joueur (par passage en équipe s'il a été
transféré). Ce n'est **pas** un log match par match : il n'y a ni date, ni
distinction domicile/extérieur nulle part dans le fichier. Voir
`README.md` section "Limites des données sources" pour l'analyse complète.

Conséquence directe : les deux questions exemples données initialement par
Sarah ("% à 3 points sur les 5 derniers matchs", "comparaison rebonds
domicile/extérieur") **ne sont pas répondables avec ces données**. Le SQL
Tool est conçu pour le détecter et répondre `NO_DATA: <raison>` plutôt que
d'halluciner un résultat — voir le comportement attendu en fin de document.

## Schéma

```
teams(team_code PK, team_name)
player_season_stats(id PK, player_name, team_code FK, age, games_played, wins, losses,
    min_avg, pts_total, fgm, fga, fg_pct, tpm, tpa, tp_pct, ftm, fta, ft_pct,
    oreb, dreb, reb, ast, tov, stl, blk, pf, fp, dd2, td3, plus_minus,
    off_rtg, def_rtg, net_rtg, ast_pct, ast_to, ast_ratio, oreb_pct, dreb_pct,
    reb_pct, to_ratio, efg_pct, ts_pct, usg_pct, pace, pie, poss)
team_summary(team_code PK FK, nb_players, total_points)
reports(report_id PK, team_code NULL, player_name NULL, report_date, author, category, content)  -- vide actuellement
```

`pts_total`, `fgm`, `fga`, `ftm`, `fta`, `oreb`, `dreb`, `reb`, `ast`, `tov`,
`stl`, `blk`, `pf`, `fp`, `poss` sont des **cumuls sur toute la saison**, pas
des moyennes par match — malgré ce qu'indique (à tort) la feuille
"Dictionnaire des données" du fichier Excel pour la colonne PTS. Pour une
moyenne par match : `total / games_played`.

## 1. Meilleur % à 3 points de la saison (avec un minimum de tentatives)

```sql
SELECT player_name, team_code, tpm, tpa, tp_pct
FROM player_season_stats
WHERE tpa >= 50   -- garde-fou : évite les faux positifs sur petit échantillon
ORDER BY tp_pct DESC
LIMIT 10;
```

## 2. Top scoreurs en moyenne par match

```sql
SELECT player_name, team_code,
       ROUND(pts_total * 1.0 / NULLIF(games_played, 0), 1) AS pts_per_game
FROM player_season_stats
WHERE games_played > 0
ORDER BY pts_per_game DESC
LIMIT 5;
```

## 3. Équipe ayant marqué le plus de points au total sur la saison

```sql
SELECT ts.team_code, t.team_name, ts.total_points
FROM team_summary ts
JOIN teams t ON t.team_code = ts.team_code
ORDER BY ts.total_points DESC
LIMIT 5;
```

## 4. Meilleurs passeurs en moyenne par match (avec seuil de matchs joués)

```sql
SELECT player_name, team_code,
       ROUND(ast * 1.0 / NULLIF(games_played, 0), 1) AS ast_per_game
FROM player_season_stats
WHERE games_played >= 10
ORDER BY ast_per_game DESC
LIMIT 3;
```

## 5. Impact global d'un joueur (PIE, ratings avancés)

```sql
SELECT player_name, team_code, pie, off_rtg, def_rtg, net_rtg
FROM player_season_stats
WHERE games_played >= 20
ORDER BY pie DESC
LIMIT 10;
```

## 6. Comparaison entre deux joueurs nommés explicitement

```sql
SELECT player_name, team_code, pts_total, reb, ast, fg_pct, tp_pct
FROM player_season_stats
WHERE player_name IN ('Nom Joueur 1', 'Nom Joueur 2');
```

## Questions NON répondables avec ce schéma (comportement attendu : NO_DATA)

```
Q: Quel joueur a le meilleur % à 3 points sur les 5 derniers matchs ?
SQL: NO_DATA: aucune donnée par match n'existe dans cette base.

Q: Compare les rebonds de l'équipe à domicile et à l'extérieur.
SQL: NO_DATA: aucune colonne domicile/extérieur n'existe dans cette base.
```

## Limites connues du mapping NL → SQL

- Les noms de joueurs doivent correspondre exactement à `player_name` en
  base (pas de résolution floue : "Steph" ne matchera pas "Stephen Curry").
- Un joueur transféré en cours de saison a plusieurs lignes (une par
  équipe) : une question du type "total de la saison pour X" doit agréger
  ces lignes (`SUM(...) GROUP BY player_name`), sinon on ne récupère que le
  passage dans une seule équipe.
- `wins`/`losses` dans `player_season_stats` reflètent le bilan de l'équipe
  du joueur sur les matchs auxquels il a contribué selon la source — à
  confirmer avec Sarah si l'usage prévu est différent.
- Le garde-fou `SQL_TOOL_MAX_ROWS` peut tronquer des résultats sur des
  questions très larges ("liste tous les joueurs...").
