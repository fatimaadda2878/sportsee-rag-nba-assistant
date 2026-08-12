# SportSee – Assistant IA d'analyse de performance NBA (RAG + SQL)

Prototype fiabilisé d'un assistant conversationnel pour coachs/analystes,
combinant recherche vectorielle sur des archives texte (rapports, discussions
Reddit) et un Tool SQL pour répondre à des questions statistiques précises.

## Architecture

```
sportsee-rag/
├── MistralChat.py          # Application Streamlit (UI + orchestration RAG/SQL)
├── indexer.py               # Construit l'index Faiss à partir de inputs/
├── load_excel_to_db.py       # Ingestion Excel -> base SQL (teams/player_season_stats/team_summary)
├── evaluate_ragas.py         # Audit RAGAS (mode before = texte seul, after = texte+SQL)
├── utils/
│   ├── config.py             # Configuration centralisée (.env)
│   ├── data_loader.py        # Extraction de texte (PDF/DOCX/TXT/CSV/Excel), OCR fallback
│   ├── vector_store.py        # Chunking, embeddings Mistral, index Faiss, recherche
│   ├── mistral_client.py      # Wrapper SDK Mistral v1.x (chat + embeddings)
│   ├── schemas.py             # Modèles Pydantic (chunks, lignes Excel, SQL Tool, tests)
│   ├── db.py                  # Modèles SQLAlchemy (teams/player_season_stats/team_summary/reports)
│   ├── sql_tool.py            # Génération NL->SQL (few-shot) + exécution sécurisée
│   ├── router.py              # Routage Pydantic AI : la question nécessite-t-elle le SQL Tool ?
│   └── observability.py       # Wrapper Pydantic Logfire (no-op si non configuré)
├── tests/
│   └── test_questions.py      # Jeu de questions métier catégorisées (simples/complexes/bruitées)
├── docs/
│   └── sql_examples.md        # Schéma SQL détaillé + requêtes types
├── data/                      # (à créer) fichier Excel source
├── inputs/                    # (à créer) archives texte (PDF Reddit, rapports...)
├── vector_db/                 # (générée) index Faiss + chunks
├── database/                  # (générée) base SQLite
├── reports/                   # (générée) CSV de résultats d'évaluation
├── requirements.txt / requirements-ocr.txt (optionnel)
├── .env.example
└── .gitignore
```

## Installation (environnement reproductible)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # puis renseigner MISTRAL_API_KEY (obligatoire)
```

Python 3.12 recommandé. L'OCR (fallback PDF scanné) est optionnel et lourd
(`torch`/`torchvision` via `easyocr`) : `pip install -r requirements-ocr.txt`
seulement si nécessaire et si l'espace disque le permet.

## Utilisation

```bash
# 1. Placer les archives texte (PDF Reddit, rapports...) dans inputs/
# 2. Construire l'index vectoriel
python indexer.py

# 3. Placer le fichier Excel source dans data/regular_NBA.xlsx
#    et créer le dossier database/ s'il n'existe pas encore (mkdir database)
python load_excel_to_db.py --excel-file data/regular_NBA.xlsx

# 4. Lancer l'application
streamlit run MistralChat.py

# 5. Auditer les performances (Étape 1 puis Étape 3)
python evaluate_ragas.py --mode before --output reports/eval_before.csv
python evaluate_ragas.py --mode after  --output reports/eval_after.csv
```

## ⚠️ Limites des données sources (à lire avant d'interpréter les résultats)

Le mapping Excel de `load_excel_to_db.py` a été **validé le 11/08/2026** sur
le vrai fichier `regular_NBA.xlsx` (feuilles, colonnes, recoupement manuel de
plusieurs lignes, ingestion réelle testée : 30 équipes + 569 joueurs insérés
avec succès) — ce n'est plus une hypothèse. Mais l'inspection a révélé un
écart important avec les questions métier envisagées initialement :

**Le fichier contient des statistiques agrégées sur toute la saison
régulière (une ligne par joueur, feuille "Données NBA", 570 lignes), pas un
log match par match.** Il n'y a ni colonne date, ni distinction
domicile/extérieur nulle part dans le fichier. En conséquence :

- ❌ **"Quel joueur a le meilleur % à 3 points sur les 5 derniers matchs ?"**
  — irréalisable : aucune notion de "match" individuel dans les données.
- ❌ **"Compare les rebonds de l'équipe à domicile et à l'extérieur"**
  — irréalisable : aucune colonne domicile/extérieur.
- ✅ Restent réalisables : classements/agrégations sur la saison entière
  (meilleur % à 3 points de la saison, top scoreurs par match en moyenne,
  comparaison de deux joueurs, total de points par équipe...). Voir
  `docs/sql_examples.md` pour la liste complète.

Le SQL Tool (`utils/sql_tool.py`) est conçu pour **détecter ce cas et
répondre "donnée non disponible" plutôt que d'halluciner un résultat** (voir
le mécanisme `NO_DATA` dans le prompt de génération SQL). Les cas de test
T08/T09 (`tests/test_questions.py`) vérifient explicitement ce comportement.

**Recommandation pour Sarah/l'équipe métier** : si les questions "par match"
et "domicile/extérieur" restent prioritaires pour les coachs, il faudra soit
obtenir un fichier avec une granularité match par match (avec date et
home/away), soit reformuler les cas d'usage autour de moyennes saison — ce
que fait déjà ce prototype.

D'autres feuilles présentes dans le fichier : "Equipe" (code -> nom complet
d'équipe, ingérée dans `teams`), "Analyse" (résumé équipe fourni par la
source, ingéré dans `team_summary`), "Analyse Vide" (même forme qu'"Analyse"
mais vide à l'inspection, non ingérée), et "Dictionnaire des données" (sert
de référence pour le mapping, non ingérée en base). Note : une ligne
d'en-tête textuelle dupliquée traîne aussi dans la feuille "Données NBA"
elle-même — elle est rejetée automatiquement par la validation Pydantic (1
ligne sur 570 lors du test réel), pas une anomalie à corriger.

## Observabilité (Pydantic Logfire)

Chaque étape de la chaîne (chunking, embeddings, recherche vectorielle,
routage, appel SQL, génération LLM) est instrumentée via `utils/observability.py`.
Sans `LOGFIRE_TOKEN` configuré, les traces s'affichent simplement en console
(mode dégradé, aucun crash). Avec un token (https://logfire.pydantic.dev),
vous obtenez un dashboard pas-à-pas de chaque requête utilisateur.

## Autres limites connues (transparence méthodologique)

1. **`evaluate_ragas.py` n'a pas encore été exécuté pour de vrai** : aucun
   score RAGAS réel n'est disponible dans ce livrable à ce stade. Le script
   est fonctionnel et prêt à l'emploi une fois `MISTRAL_API_KEY` configurée
   et les données chargées (l'ingestion SQL, elle, a été validée en réel).
   Voir le rapport joint pour la méthodologie complète et le tableau à remplir.
2. **Juge RAGAS** : par défaut, `ragas.evaluate()` s'appuie sur un LLM juge
   OpenAI (d'où la dépendance `openai` installée via `ragas`), ce qui plante
   avec `ValidationError: Did not find openai_api_key` en l'absence de clé
   OpenAI. Ce projet n'utilisant que Mistral, `evaluate_ragas.py` branche
   désormais explicitement un juge Mistral (`langchain_mistralai.ChatMistralAI`
   + `MistralAIEmbeddings`, package `langchain-mistralai` ajouté à
   `requirements.txt`) — aucune clé OpenAI n'est nécessaire.
3. **Résolution floue des noms** (ex: "Steph" -> "Stephen Curry") n'est pas
   implémentée dans le SQL Tool — voir `docs/sql_examples.md`.
4. **Joueurs transférés en cours de saison** apparaissent sur plusieurs
   lignes (une par équipe) dans `player_season_stats` : une question "total
   saison pour X" doit agréger ces lignes (`GROUP BY player_name`).

## Tests

```bash
pytest tests/
```
