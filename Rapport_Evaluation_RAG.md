# Rapport de mise en place et d'évaluation du système RAG — SportSee NBA Analyst AI

**Mission** : Évaluez les performances d'un LLM
**Auteure** : Fatima Adda-Rezig

---

## 1. Contexte et objectifs

Sarah (product owner) souhaite un assistant conversationnel destiné aux coachs et analystes NBA, capable de répondre à deux types de questions :

- des questions **qualitatives**, à partir d'archives texte (discussions Reddit r/nba, rapports) ;
- des questions **quantitatives**, à partir d'une base de statistiques joueurs/équipes (fichier `regular_NBA.xlsx`).

L'objectif de cette mission est double : construire un prototype fonctionnel combinant recherche vectorielle (RAG) et interrogation de base de données (SQL Tool), puis **évaluer objectivement ses performances** avec le framework RAGAS, avant et après l'ajout du SQL Tool, afin de mesurer l'apport réel de cet enrichissement.

## 2. Architecture du système

```
Question utilisateur
        │
        ▼
   Routeur (Pydantic AI) ──► la question nécessite-t-elle des données chiffrées ?
        │                                    │
        ▼                                    ▼
Recherche vectorielle (FAISS)          SQL Tool (LangChain NL → SQL)
   sur les archives texte              + garde-fous custom, sur PostgreSQL
        │                                    │
        └──────────────┬─────────────────────┘
                        ▼
              Génération de la réponse
           (Mistral, contexte texte + chiffré)
```

**Composants principaux** :

| Composant | Rôle |
|---|---|
| `indexer.py` | Chunking (1500 caractères, 150 de chevauchement) + embeddings Mistral (`mistral-embed`) + index FAISS, à partir des archives texte de `inputs/` |
| `load_excel_to_db.py` | Ingestion du fichier Excel source vers une base PostgreSQL (`teams`, `player_season_stats`, `team_summary`, `reports`) |
| `utils/router.py` | Détermine si une question nécessite le SQL Tool et/ou un graphique (routage Pydantic AI) |
| `utils/sql_tool.py` | Génération de requêtes SQL via LangChain (`create_sql_query_chain` + `ChatMistralAI`) + exécution sécurisée |
| `utils/plot_tool.py` | Génération dynamique de graphiques (barres/courbe/camembert) à partir des données déjà validées par le SQL Tool |
| `utils/vector_store.py` | Recherche vectorielle (top-k=5) dans l'index FAISS |
| `MistralChat.py` | Application Streamlit (UI + orchestration) |
| `evaluate_ragas.py` | Script d'audit RAGAS, modes `before` (texte seul) et `after` (texte + SQL Tool) |
| `tests/test_guardrails.py` | Tests unitaires (pytest) du routeur, du SQL Tool, du PlotTool et des garde-fous de validation — complémentaire à l'évaluation RAGAS ci-dessous, sans appel LLM ni base de données |
| `utils/observability.py` | Instrumentation Pydantic Logfire (traçage de chaque étape : chunking, recherche vectorielle, appel SQL, génération) |

**Sources de données** :
- 4 threads Reddit r/nba (discussions sur les playoffs, sentiment des fans, débats statistiques) → indexés dans `inputs/`
- `regular_NBA.xlsx` : statistiques agrégées de la saison régulière, 30 équipes et 569 lignes joueur/passage en équipe

### 2.1 SQL Tool : génération NL → SQL via LangChain

La génération de la requête SQL à partir de la question en langage naturel s'appuie sur LangChain : `create_sql_query_chain`, associé à `SQLDatabase` (introspection du schéma PostgreSQL via SQLAlchemy) et `ChatMistralAI`. Un repli automatique et transparent sur un appel direct au SDK Mistral est prévu si la chaîne LangChain échoue à s'initialiser ou à répondre — même philosophie de dégradation gracieuse que le routeur heuristique et le fallback OCR (section 8.1).

Choix architectural : LangChain est utilisé uniquement pour la *génération* de la requête SQL, jamais pour son *exécution*. `create_sql_query_chain` renvoie une chaîne de caractères SQL sans l'exécuter — contrairement à `create_sql_agent`, qui exécute lui-même la requête dans sa propre boucle d'agent, ce qui rendrait beaucoup plus difficile l'application des garde-fous de sécurité (`_is_safe_select`, `_uses_only_values_from_question`, `_enforce_limit`, détection `NO_DATA`). Ceux-ci restent appliqués systématiquement en post-traitement, entre la génération LangChain et l'exécution SQLAlchemy — aucun garde-fou n'est affaibli ou contourné par ce choix.

### 2.2 Base de données : PostgreSQL

La base de données applicative est PostgreSQL (`SQL_DATABASE_URL` dans `utils/config.py`). Le schéma relationnel (`utils/db.py`) est conçu pour être agnostique du dialecte SQL via SQLAlchemy : aucune modification du code ORM n'est nécessaire pour basculer d'un moteur à l'autre, seule la configuration change. SQLite reste disponible en dépannage (démo hors-ligne sans serveur disponible) en changeant uniquement `DATABASE_URL` dans `.env`.

## 3. Méthodologie d'évaluation

### 3.1 Jeu de questions de test

13 questions ont été construites dans `tests/test_questions.py`, réparties en 7 catégories, afin de couvrir des cas d'usage variés et représentatifs des besoins de Sarah :

| Catégorie | Questions | Objectif |
|---|---|---|
| `simple_texte` | T01, T02 | Question qualitative directe, réponse dans un seul chunk |
| `complexe_texte` | T03 | Nécessite de croiser plusieurs threads Reddit |
| `bruite_texte` | T04, T05 | Robustesse au bruit orthographique / question partiellement hors-sujet |
| `simple_chiffre` | T06, T07 | Agrégation simple sur la base SQL |
| `complexe_chiffre` | T08, T09, T10, T10b | Agrégation multicritère, y compris deux cas volontairement **irréalisables** (T08, T09) pour tester la détection `NO_DATA` |
| `mixte_texte_chiffre` | T11 | Nécessite à la fois le contexte texte ET le SQL Tool |
| `hors_perimetre` | T12 | Question hors sujet NBA, doit être déclinée poliment |

Les questions T01 à T05 et T11 ont été construites (et vérifiées manuellement) à partir du contenu réel des threads Reddit indexés, avec les vrais noms d'équipes et de joueurs cités par les fans (Orlando Magic — Paolo Banchero, Franz Wagner ; Minnesota Timberwolves — Anthony Edwards ; Detroit Pistons — Cade Cunningham ; Indiana Pacers — Tyrese Haliburton, Pascal Siakam ; Oklahoma City Thunder), plutôt que des `ground_truth` génériques, afin que l'évaluation RAGAS soit comparée à une vérité de terrain fiable.

✅ **Couverture des runs conservés** : `reports/eval_before.csv` et `reports/eval_after.csv` couvrent les 13 cas, avec un score sur les 4 métriques RAGAS pour chacun (aucune ligne ni cellule manquante). Les moyennes de la section 4 portent donc sur l'intégralité du jeu de test.

### 3.2 Métriques RAGAS retenues

Quatre métriques ont été retenues, choisies pour couvrir séparément la qualité de génération et la qualité de récupération (diagnostic indispensable pour savoir *où* corriger le système) :

- **`faithfulness`** : la réponse est-elle fidèle au contexte fourni (absence d'hallucination) ? Métrique prioritaire pour un outil destiné à des décisions métier (coachs/analystes) — une hallucination chiffrée y est particulièrement risquée.
- **`answer_relevancy`** : la réponse répond-elle effectivement à la question posée, sans digression ?
- **`context_precision`** : le contexte récupéré est-il pertinent (peu de bruit parmi les chunks renvoyés) ?
- **`context_recall`** : le contexte récupéré couvre-t-il l'information nécessaire pour répondre (`ground_truth`) ?

La séparation precision/recall permet de distinguer un problème de **génération** (le modèle hallucine malgré un bon contexte) d'un problème de **récupération** (le retrieval ne trouve pas la bonne information, ce qui pousse le modèle à halluciner faute de mieux) — distinction cruciale pour prioriser les corrections.

### 3.3 Configuration du juge

RAGAS s'appuie par défaut sur un LLM juge OpenAI. Ce projet n'utilisant que Mistral, un juge alternatif a été branché explicitement :
- LLM juge : `ChatMistralAI` (`mistral-small-latest`)
- Embeddings juge : `MistralAIEmbeddings` (`mistral-embed`)

## 4. Résultats

### 4.1 Tableau comparatif before / after, avec seuils cibles

`reports/eval_before.csv` et `reports/eval_after.csv` couvrent tous les deux les **13 cas de test au complet, avec un score sur les 4 métriques pour les 13 questions des deux côtés (13/13, sans NaN)**.

**Seuils cibles retenus** : en l'absence de seuils imposés par le brief, les valeurs ci-dessous reprennent l'ordre de grandeur usuellement recommandé pour un système RAG jugé fiable en production (≥ 0,70 sur les 4 métriques, avec une exigence renforcée à 0,80 sur `faithfulness` compte tenu du risque d'hallucination sur un chatbot d'analyse de données chiffrées). Ils servent de repère d'interprétation, pas de critère de blocage automatique — voir l'analyse sous le tableau.

| Métrique | Seuil cible | Before (n=13/13) | After (n=13/13) | Delta | Seuil atteint (after) ? |
|---|---|---|---|---|---|
| faithfulness | ≥ 0,80 | 0,867 ✅ | 0,770 | -0,097 | ❌ |
| answer_relevancy | ≥ 0,70 | 0,295 ❌ | 0,521 | **+0,226** | ❌ |
| context_precision | ≥ 0,70 | 0,274 ❌ | 0,379 | **+0,105** | ❌ |
| context_recall | ≥ 0,70 | 0,346 ❌ | 0,577 | **+0,231** | ❌ |

`answer_relevancy`, `context_precision` et `context_recall` progressent tous nettement en mode `after`, confirmant l'apport du SQL Tool. `faithfulness` reste plus élevée en `before` (0,867 vs 0,770) : les réponses de refus/clarification correctes (T06, T08, T09) sont mal notées par RAGAS — voir 4.2.

**Lecture honnête par rapport aux seuils** : aucune métrique n'atteint son seuil cible en mode `after` sur ce jeu de 13 questions. Deux facteurs limitent directement la portée de ce résultat, tous deux documentés en 4.2 : (1) RAGAS note très mal les réponses de refus légitimes (`NO_DATA`, T08/T09) et les demandes de clarification (T06) — 4 des 13 cas sur 13 sont volontairement conçus pour déclencher ce type de réponse, ce qui tire mécaniquement `faithfulness` et `answer_relevancy` vers le bas alors que le comportement métier est correct ; (2) l'échantillon (13 questions) est trop restreint pour une mesure stable au sens statistique. La progression relative (`answer_relevancy` +0,226, `context_recall` +0,231, `context_precision` +0,105) reste néanmoins le signal le plus fiable de ce rapport : elle démontre l'apport du SQL Tool indépendamment du seuil absolu. Pour une mise en production, ce rapport recommande un jeu de test élargi (50+ questions) et une métrique de type "taux de refus correctement identifiés" en complément de RAGAS, qui n'est pas conçu pour évaluer ce cas.

### 4.2 Analyse détaillée (exemples vérifiés ligne par ligne dans les CSV)

**Ce qui s'améliore avec le SQL Tool** — `answer_relevancy`, `context_precision` et `context_recall` progressent tous nettement, confirmant que les questions chiffrées et mixtes ne sont pas répondables correctement avec le texte seul.

**Un exemple d'hallucination en mode `before`, T02** : à la question *« Que disent les fans du duo de jeunes ailiers évoqué dans les threads playoffs ? »*, le système en mode texte seul répond en citant **Anthony Edwards et Jaden McDaniels (Wolves)**, alors que le duo réellement évoqué dans le thread indexé est **Paolo Banchero et Franz Wagner (Orlando Magic)**. `context_recall = 0.0` : le retrieval n'a jamais récupéré le bon chunk, noyé parmi des chunks d'un autre thread (débat statistique sur Reggie Miller) sans rapport avec la question. Exemple probant des limites du prototype texte seul, à conserver pour la soutenance.

**Un biais de retrieval qui persiste même avec le SQL Tool, T11** : sur la question mixte *« Le joueur qui impressionne le plus les fans en playoffs a-t-il aussi les meilleures stats à 3 points ? »*, la recherche vectorielle ne récupère que des chunks du débat "Reggie Miller GOAT", sans lien avec la question. La réponse générée identifie donc à tort **Reggie Miller** comme le joueur qui impressionne le plus les fans, et admet ne pas avoir les stats à 3 points en playoffs. `context_precision = 0.0` et `context_recall = 0.0` : ajouter le SQL Tool n'aide pas si la recherche textuelle en amont ramène le mauvais contexte — la qualité du retrieval reste un facteur limitant pour les questions mixtes.

**Le garde-fou anti-hallucination de valeur, T06** : la question *« Combien de points au total un joueur donné a-t-il marqués cette saison régulière ? »* ne nomme aucun joueur. `utils/sql_tool.py::_uses_only_values_from_question` rejette toute requête générée dont un littéral texte (nom de joueur, équipe...) ne partage aucun mot avec la question d'origine — le SQL Tool ne peut donc pas inventer de sa propre initiative un `WHERE player_name = '...'`. La réponse du système est : *« La question posée ne fournit pas le nom du joueur dont vous souhaitez connaître le total de points marqués en saison régulière. Veuillez préciser le nom du joueur pour que je puisse répondre avec précision. »* — comportement correct.

Effet contre-intuitif sur les scores : cette demande de clarification obtient `faithfulness = 0.8` et `answer_relevancy`/`context_recall = 0.0` (une demande de clarification ne "répond" à rien de mesurable pour RAGAS). Même schéma que T08/T09 ci-dessous : le comportement métier est correct, la métrique RAGAS le pénalise — un signal à interpréter avec prudence, pas comme un défaut du système.

**`faithfulness` reste imparfait sur les réponses chiffrées courtes, T07** : la réponse *« La moyenne de rebonds par match, toutes équipes confondues, est de 3.6. »* — exacte et directement issue du résultat SQL fourni en contexte — obtient un score `faithfulness` variable d'une exécution à l'autre (la variance vient du juge LLM, non déterministe malgré `temperature=0.0`) : une limite de mesure à traiter comme telle plutôt qu'un signal fiable sur ce cas précis.

**Les refus `NO_DATA` sont corrects mais mal notés par RAGAS, T08 et T09** : sur ces deux cas volontairement irréalisables, le système répond correctement et clairement que la donnée n'est pas disponible (ex. T08 : *« La donnée n'est pas disponible dans la base actuelle, car les statistiques ne sont fournies qu'à l'échelle de la saison entière et non par match. »*), conformément au comportement attendu. `faithfulness = 0.0` et `answer_relevancy = 0.0` dans les deux cas : la métrique RAGAS peine à évaluer une réponse de refus, qui ne "cite" pas le contexte texte fourni. Le comportement métier est correct ; c'est la métrique qui n'est pas adaptée à ce type de réponse — point à documenter comme limite méthodologique plutôt qu'à corriger dans le code.

**Un classement fiable grâce à une ingestion idempotente, T10** : la requête *« Quels sont les 3 meilleurs passeurs en moyenne par match... »* (`ORDER BY ast_per_game DESC LIMIT 3`) renvoie 3 joueurs distincts (*« Trae Young avec 11,6 passes... Nikola Jokić à 10,2... Tyrese Haliburton avec 9,2 »*), avec `faithfulness = 1.0` et `context_recall = 1.0`. Ce résultat repose sur `load_excel_to_db.py`, qui purge la table `player_season_stats` avant chaque réinsertion : sans cette purge (table à clé auto-incrémentée, sans contrainte d'unicité métier), relancer l'ingestion plusieurs fois dupliquerait les lignes et fausserait tout classement agrégé.

## 5. Limites

### 5.1 Limites des données sources

Le fichier `regular_NBA.xlsx` contient des **statistiques agrégées sur la saison régulière complète** (une ligne par joueur), sans granularité par match ni distinction domicile/extérieur. Deux cas d'usage cités initialement par Sarah sont de fait **irréalisables avec ces données** :
- « Quel joueur a le meilleur % à 3 points sur les 5 derniers matchs ? »
- « Compare les rebonds de l'équipe à domicile et à l'extérieur. »

Le SQL Tool est conçu pour détecter ce cas et répondre `NO_DATA` plutôt que d'halluciner un résultat approximatif. Vérifié par les cas de test T08/T09 : le système répond bien par un refus explicite et correct dans les deux cas (voir 4.2), même si la métrique `faithfulness` RAGAS les note à 0,0 (limite de la métrique sur les réponses de refus, pas un défaut du comportement métier). Si ces cas d'usage restent prioritaires, il faudra obtenir de Sarah un fichier à granularité match par match.

### 5.2 Limites de l'évaluation RAGAS

- Le juge Mistral, bien que fonctionnel après adaptation, n'est pas le cas d'usage d'origine de RAGAS (conçu autour d'OpenAI) : certains comportements par défaut (multi-complétions) nécessitent des adaptations (voir 3.3).
- `answer_relevancy` reste sensible à la longueur/forme des réponses (pénalise les réponses courtes et factuelles par rapport à des réponses longues et discursives), un biais à interpréter avec prudence plutôt qu'un signal de qualité brut.
- `faithfulness`, sur des réponses purement chiffrées, dépend de la formulation exacte de la réponse (phrase complète vs valeur isolée) — un point de fragilité de la métrique plus que du système évalué.
- Aucune métrique ne mesure ici la latence ni le coût par requête, deux dimensions pourtant pertinentes pour un usage en production (à envisager pour un futur monitoring).
- Le juge RAGAS/Mistral peut occasionnellement échouer à noter une métrique sur une question précise (`NaN` plutôt qu'une erreur bloquante), sans que `evaluate_ragas.py` ne le signale explicitement dans les logs (le `.mean()` pandas les ignore silencieusement) — une vérification manuelle du nombre de valeurs non-nulles par colonne est nécessaire avant de publier des moyennes, sans quoi la taille d'échantillon réelle par métrique reste invisible.

### 5.3 Limites de l'échantillon de test

13 questions est un échantillon volontairement restreint pour un prototype, suffisant pour un premier audit avant/après mais insuffisant pour une évaluation statistiquement robuste en production. Il ne couvre pas non plus la robustesse à un changement de corpus (nouveaux threads Reddit) ou de modèle de génération — deux axes de sensibilité à anticiper (voir section 6).

## 6. Choix techniques et sensibilité du système (éléments de discussion)

**Pourquoi FAISS + embeddings Mistral plutôt qu'un autre retriever ?** Corpus de taille modeste (quelques threads Reddit), FAISS en local évite une dépendance à un service de vector store managé, cohérent avec un prototype. Le choix serait à revoir (retriever hybride BM25 + dense, reranking) si le corpus grossissait significativement.

**Pourquoi ces 4 métriques RAGAS et pas d'autres ?** Elles couvrent à la fois la qualité de génération (faithfulness, answer_relevancy) et la qualité de récupération (context_precision, context_recall), ce qui permet de diagnostiquer précisément où se situe un problème plutôt que d'avoir un score agrégé opaque — essentiel pour guider les itérations futures.

**Sensibilité à un changement de corpus** : chaque nouvel ajout de contenu dans `inputs/` nécessite un re-passage d'`indexer.py` (l'index FAISS n'est pas mis à jour automatiquement). Un corpus plus volumineux ou plus bruité dégraderait probablement `context_precision` (plus de chunks concurrents pour un même sujet), justifiant à terme un mécanisme de reranking.

**Sensibilité à un changement de modèle de génération** : `MODEL_NAME` (actuellement `mistral-small-latest`) est centralisé dans `utils/config.py`. Changer de modèle nécessiterait de relancer cette même campagne d'évaluation RAGAS avant/après pour vérifier que les gains mesurés se maintiennent — c'est précisément l'intérêt d'avoir industrialisé cette évaluation en script reproductible (`evaluate_ragas.py`) plutôt qu'en test manuel ponctuel.

**Suivi dans le temps / intégration au monitoring** : chaque étape du pipeline (chunking, recherche vectorielle, routage, appel SQL, génération) est déjà instrumentée via Pydantic Logfire (`utils/observability.py`), avec un dashboard consultable en continu une fois `LOGFIRE_TOKEN` configuré. Pour un suivi dans la durée, il est recommandé de programmer `evaluate_ragas.py` en tâche récurrente (ex. à chaque changement de corpus ou de modèle) et de conserver l'historique des CSV de résultats (`reports/`) pour tracer l'évolution des 4 métriques dans le temps.

## 7. Conclusion et recommandations

L'ajout du SQL Tool améliore mesurablement le système sur la comparaison finale, strictement appariée à 13 cas et sans valeur manquante des deux côtés (answer_relevancy +0,226, context_recall +0,231, context_precision +0,105), confirmant l'intérêt de l'enrichissement chiffré pour répondre aux besoins métier de Sarah. `faithfulness` recule (-0,097). Cet écart a été investigué cas par cas (section 4.2) et attribué principalement à une limite de la métrique RAGAS sur les réponses de refus/clarification (`NO_DATA`, T06, T08/T09) et sur les réponses chiffrées courtes (T07) : le comportement métier est correct à chaque fois, mais RAGAS note ces réponses plus sévèrement qu'une réponse chiffrée fautive mais bien formulée — un artefact de mesure documenté et récurrent sur ce projet, pas une dégradation réelle de la qualité perçue par l'utilisateur.

**Recommandations pour la suite** :
1. Ajouter une métrique/vérification dédiée à la détection correcte des refus et clarifications, en complément de RAGAS, pour ne plus être aveugle sur ce comportement pourtant souhaité (T06, T08, T09 sont corrects en pratique sans que `faithfulness`/`answer_relevancy` ne le reflète).
2. Reformuler le cas de test T06 avec un nom de joueur explicite, pour disposer aussi d'un cas nominal vérifiant le bon fonctionnement du SQL Tool sur une question non ambiguë.
3. Élargir le jeu de test au-delà de 13 questions pour fiabiliser les scores absolus.
4. Obtenir de Sarah un fichier à granularité match par match si les cas d'usage "5 derniers matchs" / "domicile-extérieur" restent prioritaires.
5. Configurer `LOGFIRE_TOKEN` en environnement de production pour un suivi continu des performances.
6. Reproduire cette évaluation à chaque changement significatif de corpus ou de modèle de génération.

## 8. OCR (Nanonets) et PlotTool

Deux composants supplémentaires du système, implémentés et testés au même niveau d'exigence que le RAG et le SQL Tool présentés ci-dessus : un fallback OCR pour les rapports scannés, et un outil de génération dynamique de graphiques.

### 8.1 Fallback OCR (Nanonets) pour les rapports scannés

**Contexte** : le pipeline d'ingestion (`utils/data_loader.py`) ne traite par défaut que des PDF avec une couche de texte exploitable (extraction `PyPDF2`). Un PDF scanné (image pure, sans texte sélectionnable) — cas réaliste pour des rapports d'analyse — nécessite un traitement dédié.

**Implémentation** : un fallback OCR via l'API Nanonets (`extract_text_with_ocr_nanonets`) se déclenche automatiquement lorsque l'extraction standard renvoie moins de 100 caractères. Sans clé `NANONETS_API_KEY` configurée, ce fallback est désactivé proprement (pas d'exception, pas de blocage de l'ingestion) — testé unitairement dans `tests/test_guardrails.py::TestOcrFallbackGracefulDegradation`.

**Évaluation avant/après** : aucun rapport scanné réel n'existant dans `inputs/` (uniquement des archives texte Reddit), `evaluate_ocr.py` génère un document de test synthétique reproductible — un texte de référence connu, rendu en image, puis enregistré en PDF sans couche de texte (donc illisible par l'extraction standard, comme un vrai scan). Le script mesure ensuite un score de similarité (`difflib.SequenceMatcher`) entre le texte extrait et le texte de référence :

| Mode | Caractères extraits | Score de similarité |
|---|---|---|
| Avant (PyPDF2 seul) | 0 | 0,0000 |
| Après (+ OCR Nanonets) | 413 | 0,9757 |

Le cas « avant » confirme que l'extraction standard échoue bien totalement sur un document image pur (0 caractère, comme attendu pour un vrai rapport scanné). Le cas « après », avec le fallback OCR Nanonets actif, restitue **413 caractères avec une similarité de 0,9757** au texte de référence — une amélioration de **+0,9757**, qui démontre concrètement l'apport du fallback OCR sur un cas représentatif d'un rapport scanné, sans dépendre d'un vrai document indisponible dans ce projet.

### 8.2 PlotTool : génération dynamique de graphiques

**Implémentation** : `utils/plot_tool.py` génère un graphique (barres, courbe ou camembert) lorsqu'une visualisation est explicitement demandée (`route.needs_plot`, porté par le routeur `QueryRoute`). Un invariant du modèle (`@model_validator` sur `QueryRoute`) garantit que `needs_plot=True` implique toujours `needs_sql=True`, quelle que soit la source de la décision (LLM ou heuristique de repli) — ce qui garantit que le contexte SQL utilisé pour rédiger la réponse textuelle est toujours cohérent avec les données affichées dans le graphique.

**Choix de conception** : contrairement au SQL Tool (section 2.1, qui utilise LangChain pour la génération NL → SQL), le PlotTool n'appelle pas de chaîne LangChain — et ce délibérément, pour ne pas ouvrir un second point d'hallucination de données à côté du SQL Tool déjà sécurisé. Le PlotTool réutilise exclusivement les lignes déjà validées et retournées par le SQL Tool : aucune valeur numérique n'est générée par un nouvel appel LLM. Seul le *type* de graphique est déterminé, par une heuristique de mots-clés sans appel API (même principe que le fallback heuristique du routeur, `utils/router.py::_heuristic_route`) — un choix de fiabilité délibéré, en particulier avant une démonstration en direct.

**Détection robuste des colonnes numériques** : le SQL Tool s'exécute aussi bien sur SQLite que sur PostgreSQL (section 2.2). Les deux moteurs ne renvoient pas le même type Python pour une colonne calculée (ex. `ROUND(...)`) : `float` sur SQLite, `decimal.Decimal` sur PostgreSQL (via `psycopg2`). Le PlotTool reconnaît les deux types indifféremment (`utils/plot_tool.py::_extract_labels_and_values`), afin que la génération de graphique reste fiable quel que soit le moteur de base de données configuré.

Testé unitairement (`tests/test_guardrails.py::TestPlotToolChartType`, `TestPlotToolNoDataFabrication`, `TestQueryRoutePlotRequiresSql`) : choix du type de graphique, extraction des colonnes label/valeur (y compris `decimal.Decimal`), cohérence texte/graphique garantie par l'invariant du modèle, et surtout — le garde-fou central — retour d'une erreur explicite plutôt qu'un graphique fabriqué lorsque le SQL Tool n'a pas de donnée exploitable.

## Annexe — Jeu de questions de test complet

Les 13 cas ci-dessous sont définis dans `tests/test_questions.py`. Les runs finaux conservés (section 4.1) couvrent les 13 cas des deux côtés (`before` et `after`), sur les 4 métriques RAGAS, sans valeur manquante.

| ID | Catégorie | Question |
|---|---|---|
| T01 | simple_texte | Quelles équipes des playoffs ont le plus impressionné les fans récemment ? |
| T02 | simple_texte | Que disent les fans du duo de jeunes ailiers évoqué dans les threads playoffs ? |
| T03 | complexe_texte | En croisant les différents threads Reddit, quel est le sentiment général sur le niveau de compétitivité des playoffs cette année ? |
| T04 | bruite_texte | dites moi ce ke les gens pensen des playoff cet année svp?? |
| T05 | bruite_texte | Et sinon, niveau ambiance, c'est comment cette saison par rapport à la boxe ? |
| T06 | simple_chiffre | Combien de points au total un joueur donné a-t-il marqués cette saison régulière ? |
| T07 | simple_chiffre | Quelle est la moyenne de rebonds par match, toutes équipes confondues ? |
| T08 | complexe_chiffre | Quel joueur a le meilleur pourcentage de réussite à 3 points sur les 5 derniers matchs ? (irréalisable, test NO_DATA) |
| T09 | complexe_chiffre | Compare les statistiques de rebonds de l'équipe à domicile et à l'extérieur. (irréalisable, test NO_DATA) |
| T10 | complexe_chiffre | Quels sont les 3 meilleurs passeurs en moyenne par match cette saison (au moins 10 matchs joués) ? |
| T10b | complexe_chiffre | Quel joueur a le meilleur pourcentage à 3 points cette saison, avec au moins 50 tentatives ? |
| T11 | mixte_texte_chiffre | Le joueur qui impressionne le plus les fans en playoffs a-t-il aussi les meilleures stats à 3 points ? |
| T12 | hors_perimetre | Peux-tu me donner la recette d'un cookie au chocolat ? |
