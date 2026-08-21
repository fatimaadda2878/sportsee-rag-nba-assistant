# 🏀 SportSee --- NBA Analyst AI

> Assistant conversationnel NBA combinant **RAG**, **recherche
> vectorielle FAISS**, **routage intelligent** et **SQL Tool** pour
> répondre à la fois aux questions qualitatives et aux questions
> statistiques.

## Présentation

Ce projet propose un prototype d'assistant IA destiné à l'analyse de
données NBA.\
L'objectif est de dépasser les limites d'un RAG purement textuel en
combinant deux sources de connaissance complémentaires :

-   **des archives textuelles** (rapports, discussions Reddit,
    documents) interrogées par recherche vectorielle ;
-   **des données NBA structurées** interrogées via un SQL Tool pour les
    questions chiffrées.

Un routeur basé sur **Pydantic AI** détermine automatiquement si une
question nécessite du contexte textuel, une requête SQL, ou les deux. La
réponse finale est générée avec **Mistral AI** et l'ensemble du pipeline
est instrumenté avec **Pydantic Logfire**.

------------------------------------------------------------------------

## 🎯 Objectifs

Le prototype doit être capable de traiter plusieurs familles de
questions :

-   questions qualitatives simples ;
-   questions nécessitant de croiser plusieurs sources textuelles ;
-   formulations bruitées ou imprécises ;
-   questions statistiques simples ;
-   agrégations et classements plus complexes ;
-   questions mixtes nécessitant à la fois texte et SQL ;
-   questions hors périmètre ou impossibles à résoudre avec les données
    disponibles.

Le projet compare ainsi deux approches :

  Version      Pipeline
  ------------ --------------------------------------------
  **Before**   Recherche vectorielle textuelle uniquement
  **After**    Recherche vectorielle + routage + SQL Tool

------------------------------------------------------------------------

## 🧠 Architecture

``` text
                           ┌──────────────────────┐
                           │      Streamlit       │
                           │    MistralChat.py    │
                           └──────────┬───────────┘
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │    Pydantic AI       │
                           │       Router         │
                           └──────────┬───────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     │                                 │
                     ▼                                 ▼
          ┌─────────────────────┐           ┌─────────────────────┐
          │  Recherche texte    │           │      SQL Tool       │
          │ Mistral embeddings  │           │   NL → SQL sécurisé│
          │       FAISS         │           │       SQLite        │
          └──────────┬──────────┘           └──────────┬──────────┘
                     │                                 │
                     └────────────────┬────────────────┘
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │     Mistral AI       │
                           │ Génération finale    │
                           └──────────┬───────────┘
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │      Réponse         │
                           │ + SQL traçable si    │
                           │      utilisé         │
                           └──────────────────────┘

                     Observabilité : Pydantic Logfire
```

### Pipeline d'une question

1.  L'utilisateur saisit sa question dans l'interface Streamlit.
2.  `router.py` détermine si la question nécessite des données SQL et/ou
    un graphique (`needs_sql`, `needs_text_context`, `needs_plot`).
3.  Si nécessaire, la recherche vectorielle récupère jusqu'à **5
    chunks** pertinents dans FAISS.
4.  Pour une question statistique, `sql_tool.py` génère puis exécute une
    requête SQL sécurisée.
5.  Si un graphique est explicitement demandé, `plot_tool.py` génère un
    graphique (barres/courbe/camembert) à partir des lignes déjà
    retournées par le SQL Tool (voir section PlotTool ci-dessous).
6.  Le contexte textuel et/ou les résultats SQL sont injectés dans le
    prompt final.
7.  Mistral génère une réponse strictement fondée sur les informations
    récupérées.
8.  Logfire trace les principales étapes du traitement.

------------------------------------------------------------------------

## 🛠️ Stack technique

  Composant                 Technologie
  ------------------------- -------------------------------------
  Interface                 Streamlit
  LLM                       Mistral AI (`mistral-small-latest`)
  Embeddings                `mistral-embed`
  Vector store              FAISS
  Routage                   Pydantic AI
  Validation                Pydantic
  Base structurée           SQLite + SQLAlchemy
  Traitement de données     Pandas / OpenPyXL
  Évaluation                RAGAS
  Juge RAGAS                Mistral via `langchain-mistralai`
  Observabilité             Pydantic Logfire
  Tests                     Pytest
  Extraction documentaire   PyPDF2 / python-docx
  OCR (fallback)            Nanonets/Docstrange OCR (appel HTTP direct)
  Visualisation             PlotTool (Matplotlib)

------------------------------------------------------------------------

## 📁 Structure du projet

``` text
sportsee-rag-nba-assistant/
│
├── MistralChat.py              # Application Streamlit
├── indexer.py                  # Construction de l'index FAISS
├── load_excel_to_db.py         # Ingestion Excel → SQLite
├── evaluate_ragas.py           # Évaluation comparative RAGAS
├── evaluate_ocr.py             # Évaluation avant/après du fallback OCR
│
├── utils/
│   ├── config.py               # Configuration centralisée
│   ├── data_loader.py          # Extraction PDF/DOCX/TXT/CSV/Excel + fallback OCR Nanonets
│   ├── db.py                   # Modèles SQLAlchemy
│   ├── mistral_client.py       # Wrapper SDK Mistral
│   ├── observability.py        # Configuration Logfire + fallback
│   ├── plot_tool.py            # PlotTool : génération dynamique de graphiques
│   ├── router.py               # Routage Pydantic AI (needs_sql / needs_text_context / needs_plot)
│   ├── schemas.py              # Schémas Pydantic
│   ├── sql_tool.py             # NL → SQL + garde-fous
│   └── vector_store.py         # Chunking, embeddings et recherche FAISS
│
├── tests/
│   ├── test_questions.py       # 13 cas métier catégorisés (jeu RAGAS)
│   └── test_guardrails.py      # Tests unitaires pytest (SQL Tool, routeur, PlotTool, OCR)
│
├── docs/
│   └── sql_examples.md         # Schéma et exemples SQL
│
├── data/
│   └── regular_NBA.xlsx        # Données NBA structurées
│
├── requirements.txt
├── .env.example
└── README.md
```

Les répertoires `inputs/`, `vector_db/`, `database/` et `reports/` sont
créés ou alimentés localement selon les étapes du pipeline et leurs
artefacts générés ne sont pas versionnés.

------------------------------------------------------------------------

## 📊 Données structurées

L'ingestion de `data/regular_NBA.xlsx` alimente notamment les tables :

-   `teams`
-   `player_season_stats`
-   `team_summary`

Le mapping a été validé sur le fichier fourni avec une ingestion de **30
équipes et 569 lignes joueur/passage en équipe** (fichier source, une
exécution propre de `load_excel_to_db.py`).

⚠️ **Bug corrigé le 17/08/2026** : `load_player_season_stats` n'était pas
idempotent (`session.add()` sans purge ni clé métier), donc relancer le
script plusieurs fois empilait les lignes. La base a ainsi contenu jusqu'à
**1707 lignes** dans `player_season_stats` (569 × 3, confirmant 3
exécutions successives) avant correction. Le script vide désormais la table
avant chaque réinsertion — relancer `python load_excel_to_db.py` une fois
pour repartir sur une base propre.

### ⚠️ Granularité des données

Le fichier contient des **statistiques agrégées sur l'ensemble de la
saison régulière**, et non un historique match par match.

Il ne contient notamment :

-   aucune date de match ;
-   aucun détail des cinq derniers matchs ;
-   aucune distinction domicile / extérieur.

Le système ne doit donc pas inventer une réponse lorsqu'une question
exige une granularité absente.

Exemples :

``` text
❌ "Quel joueur a le meilleur pourcentage à 3 points sur les 5 derniers matchs ?"
→ Donnée non disponible : absence de données match par match.

❌ "Compare les rebonds à domicile et à l'extérieur."
→ Donnée non disponible : absence de variable home/away.

✅ "Quel joueur a le meilleur pourcentage à 3 points cette saison avec au moins 50 tentatives ?"
→ Requête réalisable avec player_season_stats.
```

Le SQL Tool implémente explicitement un mécanisme `NO_DATA` afin de
signaler ces limites plutôt que de produire une requête ou un chiffre
non fondé.

------------------------------------------------------------------------

## 🔐 SQL Tool et garde-fous

Le SQL Tool transforme une question en langage naturel en requête SQL à
partir du schéma connu.

Plusieurs protections sont appliquées avant exécution :

-   validation de l'entrée avec Pydantic ;
-   requêtes **SELECT uniquement** ;
-   rejet des opérations DDL/DML ;
-   limitation du nombre de lignes retournées ;
-   détection des demandes incompatibles avec la granularité des données
    ;
-   réponse `NO_DATA` lorsque les données nécessaires n'existent pas.

L'application peut également afficher la requête SQL exécutée dans un
panneau dédié afin de rendre la réponse plus traçable.

------------------------------------------------------------------------

## 🔎 RAG textuel

Le pipeline textuel repose sur :

1.  extraction du contenu des documents ;
2.  découpage en chunks ;
3.  génération d'embeddings avec `mistral-embed` ;
4.  indexation FAISS ;
5.  recherche des chunks les plus proches de la question ;
6.  injection du contexte récupéré dans le prompt final.

Configuration actuelle :

``` text
CHUNK_SIZE = 1500 caractères
CHUNK_OVERLAP = 150 caractères
SEARCH_K = 5
EMBEDDING_MODEL = mistral-embed
```

------------------------------------------------------------------------

## 🧭 Routage avec Pydantic AI

Le routeur produit une sortie structurée :

``` python
class QueryRoute(BaseModel):
    needs_sql: bool
    needs_text_context: bool
    needs_plot: bool = False   # ajouté le 21/08/2026 (PlotTool)
    reasoning: str
```

Les questions portant sur des statistiques, pourcentages, classements,
points, rebonds, passes ou comparaisons peuvent ainsi être orientées
vers le SQL Tool. `needs_plot` n'est activé que si l'utilisateur demande
explicitement une visualisation (« graphique », « montre l'évolution »,
« trace », etc.) — jamais par défaut sur une simple question chiffrée.

Un **fallback heuristique** basé sur des mots-clés et expressions
numériques est prévu si le routage LLM échoue ou si la clé Mistral n'est
pas disponible.

------------------------------------------------------------------------

## 📊 PlotTool : génération dynamique de graphiques

Ajouté le 21/08/2026 à la demande de Sarah (« génération dynamique de
graphiques avec un PlotTool personnalisé »).

Le PlotTool (`utils/plot_tool.py`) génère un graphique (barres, courbe ou
camembert) directement dans la réponse, lorsqu'un graphique est
explicitement demandé (`route.needs_plot`).

**Choix de conception important** : le PlotTool ne génère jamais ses
propres valeurs numériques. Il réutilise exclusivement les lignes déjà
récupérées et validées par le SQL Tool (mêmes garde-fous anti-hallucination
que la section précédente) — seul le *type* de graphique est déterminé,
par une heuristique de mots-clés sans appel LLM supplémentaire (« évolution
» → courbe, « répartition » → camembert, sinon → barres), sur le même
principe que le fallback heuristique du routeur. Cela évite d'ouvrir un
second point de fabrication de données dans le pipeline.

Si le SQL Tool n'a renvoyé aucune donnée exploitable, le PlotTool renvoie
une erreur explicite plutôt qu'un graphique inventé.

------------------------------------------------------------------------

## 🖼️ OCR (fallback Nanonets) pour les rapports scannés

Ajouté le 21/08/2026 à la demande de Sarah (« remplace EasyOCR par
Nanonets OCR »). L'extraction PDF standard (`PyPDF2`) reste la méthode
principale ; si elle renvoie trop peu de texte (< 100 caractères, seuil
`OCR_FALLBACK_MIN_CHARS`), un fallback OCR via l'API Nanonets est tenté
automatiquement (`utils/data_loader.py::extract_text_with_ocr_nanonets`).

Sans `NANONETS_API_KEY` configurée dans `.env`, l'OCR est simplement
désactivé — aucune exception ne remonte, l'ingestion continue avec le
texte (éventuellement vide) de l'extraction standard.

Aucun rapport scanné réel n'étant disponible dans `inputs/` (uniquement
des archives texte Reddit), `evaluate_ocr.py` génère un document de test
synthétique reproductible (texte de référence connu, rendu en image puis
enregistré en PDF sans couche de texte) afin de produire une évaluation
avant/après honnête et reproductible :

```
python evaluate_ocr.py
```

Résultats écrits dans `reports/ocr_before_after.csv` (score de similarité
au texte de référence, avant/après activation du fallback OCR).

------------------------------------------------------------------------

## 🔭 Observabilité avec Logfire

Le pipeline est instrumenté avec **Pydantic Logfire** afin de suivre
notamment :

``` text
handle_user_question
        │
        ├── route_query
        ├── recherche vectorielle
        ├── SQL Tool
        └── llm_generate_answer
```

Lorsque `LOGFIRE_TOKEN` est configuré, les traces sont envoyées au
dashboard Logfire.

Sans token valide, `utils/observability.py` bascule vers un logger local
de secours afin que l'application reste utilisable.

### Bugs identifiés grâce à l'observabilité

L'activation réelle de Logfire a permis d'identifier deux problèmes qui
étaient auparavant masqués par le mode dégradé.

**1. Incompatibilité des appels `logfire.warning()`**

Le logger de secours exposait une méthode `warning()`, contrairement au
SDK Logfire utilisé dans le projet. Les appels concernés dans le
pipeline ont été remplacés par `logfire.info()`.

**2. Streamlit + asyncio + Pydantic AI**

`agent.run_sync()` échouait dans le thread `ScriptRunner` de Streamlit
car aucun event loop asyncio n'y était créé automatiquement.

`router.py` initialise désormais explicitement un event loop lorsqu'il
n'en existe pas avant l'appel à Pydantic AI :

``` python
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
```

Après correction, plusieurs traces `handle_user_question` ont été
observées avec succès dans Logfire sans nouvelle exception liée à ces
problèmes.

**3. Routage Pydantic AI systématiquement en échec silencieux**

`pydantic-ai` a renommé le paramètre `result_type` de `Agent(...)` en
`output_type` (et `.data` en `.output` sur le résultat) dans une version
plus récente que celle utilisée à l'écriture du code. L'ancien nom ne
provoquait pas de plantage direct, mais faisait échouer l'agent à chaque
appel — rattrapé silencieusement par le fallback heuristique de
`router.py`. Le routage LLM ne s'exécutait donc jamais réellement avant
cette correction. Corrigé dans `utils/router.py`.

**4. Base `player_season_stats` triplée par une ingestion non idempotente**

`load_excel_to_db.py::load_player_season_stats` insérait les lignes sans
purger la table au préalable, contrairement aux deux autres tables
(`teams`, `team_summary`) qui utilisent `session.merge()`. Relancer le
script plusieurs fois empilait donc les stats joueurs au lieu de les
remplacer : la base contenait 1707 lignes pour 569 joueurs réels
(exactement × 3). Corrigé en purgeant la table avant chaque réinsertion —
voir aussi `Rapport_Evaluation_RAG.md` pour l'impact sur l'évaluation
RAGAS (cas de test T10).

**5. Script d'évaluation interrompu par une erreur transitoire de l'API**

`evaluate_ragas.py` n'avait aucune tolérance aux pannes réseau (ex. `503
Service Unavailable` côté Mistral) : un seul appel en échec faisait
perdre tout le run. Ajout d'un retry avec backoff dans
`utils/mistral_client.py`, et d'un retry ciblé côté juge RAGAS pour les
questions notées `NaN` (échec de notation silencieux) dans
`evaluate_ragas.py`.

**6. Le SQL Tool pouvait halluciner une valeur non demandée**

Détecté via l'évaluation RAGAS (cas de test `T06`) : pour une question ne
nommant aucun joueur, le générateur SQL inventait de lui-même un nom
(`WHERE player_name = 'LeBron James'`) au lieu de répondre `NO_DATA` ou
de signaler l'ambiguïté. Corrigé avec un nouveau garde-fou
(`utils/sql_tool.py::_uses_only_values_from_question`) qui rejette toute
requête générée référençant une valeur absente de la question d'origine,
testé unitairement.

------------------------------------------------------------------------

# 🧪 Évaluation RAGAS

`evaluate_ragas.py` compare les deux versions du pipeline sur **13 cas
de test**.

### Mode `before`

``` bash
python evaluate_ragas.py --mode before --output reports/eval_before.csv
```

Évalue la baseline basée sur la recherche vectorielle textuelle.

### Mode `after`

``` bash
python evaluate_ragas.py --mode after --output reports/eval_after.csv
```

Évalue le pipeline enrichi avec routage et SQL Tool.

### Catégories testées

Les cas couvrent :

-   texte simple ;
-   texte complexe ;
-   texte bruité ;
-   chiffré simple ;
-   chiffré complexe ;
-   mixte texte + chiffres ;
-   hors périmètre.

Les tests `T08` et `T09` vérifient volontairement que le système sait
reconnaître une **donnée indisponible** au lieu d'halluciner une
réponse.

------------------------------------------------------------------------

## 📈 Résultats RAGAS

Quatre métriques sont calculées :

-   **Faithfulness** --- fidélité de la réponse au contexte fourni ;
-   **Answer Relevancy** --- pertinence de la réponse vis-à-vis de la
    question ;
-   **Context Precision** --- proportion de contexte récupéré réellement
    utile ;
-   **Context Recall** --- couverture des informations nécessaires à la
    réponse.

### Scores moyens

Comparaison finale (17/08/2026), strictement appariée sur les 13 cas de
test et les 4 métriques, sans valeur manquante des deux côtés (run
`after` régénéré après correction du garde-fou anti-hallucination du SQL
Tool, voir point 6 ci-dessous) :

  Métrique              Before --- texte seul   After --- routage + SQL   Évolution
  ------------------- ----------------------- ------------------------- -----------
  Faithfulness                       **0,867**                     0,673       -0,194
  Answer Relevancy                       0,295                 **0,581**   **+0,286**
  Context Precision                      0,274                 **0,403**   **+0,129**
  Context Recall                         0,346                 **0,577**   **+0,231**

Détail complet des reproductions de run, des cas de figure et de
l'analyse question par question : voir `Rapport_Evaluation_RAG.md`
(sections 4 et 5).

### Interprétation

L'ajout du routage et du SQL Tool améliore fortement la **pertinence des
réponses**, le **rappel** et la **précision du contexte** :

``` text
Answer Relevancy  : 0,295 → 0,581
Context Recall    : 0,346 → 0,577
Context Precision : 0,274 → 0,403
```

Le système enrichi récupère donc mieux les informations nécessaires,
notamment pour les questions chiffrées pour lesquelles une recherche
textuelle seule est insuffisante.

La **Faithfulness** diminue en revanche (0,867 → 0,673). Cette baisse a
été analysée cas par cas (voir `Rapport_Evaluation_RAG.md`, section 4.2)
et s'explique presque entièrement par une limite du juge RAGAS sur les
réponses de refus/clarification (`NO_DATA`, cas `T08`/`T09`, et
désormais `T06` une fois corrigé) et sur certaines réponses chiffrées
courtes (`T07`) : RAGAS note plus sévèrement une réponse de clarification
correcte qu'une réponse chiffrée fautive mais bien formulée. Corriger le
bug applicatif de `T06` (voir "Bugs identifiés grâce à l'observabilité",
point 6) a d'ailleurs *fait baisser* ce score, un effet contre-intuitif
mais cohérent avec ce biais de mesure.

------------------------------------------------------------------------

## ⚠️ Limites de l'évaluation

### Couverture before / after

Après plusieurs itérations (voir `Rapport_Evaluation_RAG.md`, section
4.3), les CSV `before` et `after` couvrent désormais les mêmes 13 cas de
test, sur les 4 métriques, sans valeur manquante — la comparaison
ci-dessus est donc strictement appariée.

### RAGAS avec Mistral

Le projet utilise **Mistral comme juge RAGAS**, et non OpenAI.

Deux adaptations ont été nécessaires.

#### `AnswerRelevancy(strictness=1)`

La configuration par défaut utilise plusieurs générations pour
`answer_relevancy`. Avec le modèle Mistral utilisé, ce fonctionnement
provoquait des échecs silencieux de la métrique.

Le projet utilise donc :

``` python
answer_relevancy = AnswerRelevancy(strictness=1)
```

#### Rate limiting

RAGAS exécute plusieurs évaluations en parallèle. Avec les limites de
l'API Mistral utilisée, cela pouvait produire des erreurs HTTP `429`.

Le script configure donc :

``` python
RunConfig(
    max_workers=2,
    max_retries=20,
    max_wait=45,
    timeout=300,
)
```

Ce compromis réduit les appels concurrents tout en conservant une durée
d'évaluation acceptable.

### Ground truths à consolider

Les réponses de référence présentes dans `tests/test_questions.py` ont
été construites pour représenter le comportement attendu du système.
Elles devront être consolidées avec une validation métier pour
transformer ce benchmark technique en évaluation de référence plus
robuste.

------------------------------------------------------------------------

## 🚀 Installation

### 1. Cloner le projet

``` bash
git clone https://github.com/fatimaadda2878/sportsee-rag-nba-assistant.git
cd sportsee-rag-nba-assistant
```

### 2. Créer l'environnement virtuel

``` bash
python -m venv venv
```

Linux / macOS :

``` bash
source venv/bin/activate
```

Windows :

``` bash
venv\Scripts\activate
```

### 3. Installer les dépendances

``` bash
pip install -r requirements.txt
```

Python **3.12** est recommandé.

------------------------------------------------------------------------

## ⚙️ Configuration

Copier le fichier d'exemple :

``` bash
cp .env.example .env
```

Sous Windows :

``` powershell
copy .env.example .env
```

Puis renseigner les variables nécessaires :

``` env
MISTRAL_API_KEY="..."
LOGFIRE_TOKEN=""
LOGFIRE_DISABLE=false
DATABASE_URL="sqlite:///database/sportsee.db"
NANONETS_API_KEY=""
```

`MISTRAL_API_KEY` est nécessaire pour le fonctionnement complet du
pipeline.

Le token Logfire est optionnel.

`NANONETS_API_KEY` est optionnelle : sans elle, le fallback OCR (rapports
scannés) est simplement désactivé, sans erreur. Compte gratuit :
<https://docstrange.nanonets.com> (clé dans le menu en haut à droite une
fois connecté — attention, différent de l'ancienne page
`app.nanonets.com/#/keys`, incompatible avec l'API actuelle).

------------------------------------------------------------------------

## ▶️ Préparer et lancer l'application

### 1. Construire l'index vectoriel

Placer les documents textuels dans `inputs/`, puis :

``` bash
python indexer.py
```

### 2. Charger les données NBA en base

Le fichier source du dépôt est :

``` text
data/regular_NBA.xlsx
```

Créer le dossier de base de données si nécessaire :

``` bash
mkdir database
```

Puis lancer :

``` bash
python load_excel_to_db.py --excel-file data/regular_NBA.xlsx
```

### 3. Démarrer Streamlit

``` bash
streamlit run MistralChat.py
```

------------------------------------------------------------------------

## ✅ Tests

Lancer les tests avec :

``` bash
pytest tests/
```

52 tests unitaires (`tests/test_guardrails.py`), sans appel API ni base de
données : garde-fous du SQL Tool, routeur, PlotTool (dont le garde-fou
anti-fabrication de données), et dégradation gracieuse de l'OCR sans clé.

Le fichier `tests/test_questions.py` sert également de benchmark métier
à l'évaluation RAGAS.

Pour évaluer concrètement l'apport du fallback OCR (avant/après, sur un
document de test synthétique généré automatiquement) :

``` bash
python evaluate_ocr.py
```

------------------------------------------------------------------------

## 🔬 Pistes d'amélioration

**Déjà livré** (initialement listé ici comme piste, réalisé depuis) :
tests unitaires dédiés au routeur, au SQL Tool et aux garde-fous
(`tests/test_guardrails.py`, 52 tests) ; fallback OCR Nanonets pour les
rapports scannés ; PlotTool pour la génération dynamique de graphiques.

Pistes restantes :

-   disposer de données NBA **match par match** avec date et statut
    domicile/extérieur ;
-   harmoniser strictement les cas présents dans les évaluations
    `before` et `after` ;
-   normaliser les résultats SQL en texte avant leur évaluation par
    RAGAS ;
-   ajouter une métrique dédiée à l'**exactitude numérique** ;
-   faire valider les ground truths par un référent métier ;
-   améliorer la résolution des noms de joueurs (`Steph` →
    `Stephen Curry`) ;
-   mieux gérer les joueurs ayant changé d'équipe en cours de saison ;
-   évaluer séparément chaque catégorie de question ;
-   tester une stratégie de routage réellement hybride lorsque texte et
    SQL sont nécessaires simultanément ;
-   étendre le PlotTool à des graphiques multi-séries (comparaison de
    plusieurs joueurs sur un même graphique).

------------------------------------------------------------------------

## 💡 Enseignements

Ce projet met en évidence une limite importante d'un RAG uniquement
vectoriel : retrouver un document pertinent ne suffit pas toujours à
répondre correctement à une question quantitative.

L'architecture hybride permet de spécialiser les outils :

``` text
RAG       → informations qualitatives et documentaires
SQL       → données structurées et calculs précis
Router    → sélection de la stratégie
Mistral   → compréhension et génération
Logfire   → observabilité et diagnostic
RAGAS     → mesure comparative des performances
```

Les résultats obtenus montrent notamment une amélioration nette de la
pertinence des réponses et du rappel du contexte après l'introduction du
routage et du SQL Tool, tout en faisant apparaître de nouvelles limites
méthodologiques dans l'évaluation automatique des réponses numériques.

------------------------------------------------------------------------

## 👩‍💻 Auteur

**Fatima Adda**

Projet réalisé dans le cadre d'un travail sur les systèmes RAG, les
agents IA et l'exploitation conjointe de données textuelles et
structurées.

------------------------------------------------------------------------

## 📌 Statut

**Prototype fonctionnel --- projet pédagogique / portfolio Data & IA**

Le système est opérationnel sur la granularité actuellement disponible
dans les données et privilégie explicitement l'absence de réponse à
l'invention d'une information non disponible.
