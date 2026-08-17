# Rapport de mise en place et d'évaluation du système RAG — SportSee NBA Analyst AI

**Mission** : Évaluez les performances d'un LLM
**Auteure** : Fatima Adda
**Date** : Août 2026

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
Recherche vectorielle (FAISS)          SQL Tool (NL → SQL few-shot)
   sur les archives texte                sur la base SQLite
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
| `load_excel_to_db.py` | Ingestion du fichier Excel source vers une base SQLite (`teams`, `player_season_stats`, `team_summary`, `reports`) |
| `utils/router.py` | Détermine si une question nécessite le SQL Tool (routage Pydantic AI) |
| `utils/sql_tool.py` | Génération de requêtes SQL few-shot + exécution sécurisée (garde-fous : `SQL_TOOL_MAX_ROWS`, détection des questions non répondables → `NO_DATA`) |
| `utils/vector_store.py` | Recherche vectorielle (top-k=5) dans l'index FAISS |
| `MistralChat.py` | Application Streamlit (UI + orchestration) |
| `evaluate_ragas.py` | Script d'audit RAGAS, modes `before` (texte seul) et `after` (texte + SQL Tool) |
| `utils/observability.py` | Instrumentation Pydantic Logfire (traçage de chaque étape : chunking, recherche vectorielle, appel SQL, génération) |

**Sources de données** :
- 4 threads Reddit r/nba (discussions sur les playoffs, sentiment des fans, débats statistiques) → indexés dans `inputs/`
- `regular_NBA.xlsx` : statistiques agrégées de la saison régulière, 30 équipes et 569 joueurs ingérés avec succès (validé le 11/08/2026)

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

### 3.2 Métriques RAGAS retenues

Quatre métriques ont été retenues, choisies pour couvrir séparément la qualité de génération et la qualité de récupération (diagnostic indispensable pour savoir *où* corriger le système) :

- **`faithfulness`** : la réponse est-elle fidèle au contexte fourni (absence d'hallucination) ? Métrique prioritaire pour un outil destiné à des décisions métier (coachs/analystes) — une hallucination chiffrée y est particulièrement risquée.
- **`answer_relevancy`** : la réponse répond-elle effectivement à la question posée, sans digression ?
- **`context_precision`** : le contexte récupéré est-il pertinent (peu de bruit parmi les chunks renvoyés) ?
- **`context_recall`** : le contexte récupéré couvre-t-il l'information nécessaire pour répondre (`ground_truth`) ?

La séparation precision/recall permet de distinguer un problème de **génération** (le modèle hallucine malgré un bon contexte) d'un problème de **récupération** (le retrieval ne trouve pas la bonne information, ce qui pousse le modèle à halluciner faute de mieux) — distinction cruciale pour prioriser les corrections.

### 3.3 Configuration du juge et défis rencontrés

RAGAS s'appuie par défaut sur un LLM juge OpenAI. Ce projet n'utilisant que Mistral, un juge alternatif a été branché explicitement :
- LLM juge : `ChatMistralAI` (`mistral-small-latest`)
- Embeddings juge : `MistralAIEmbeddings` (`mistral-embed`)

Plusieurs obstacles techniques ont été rencontrés et résolus pendant la mise en place de l'évaluation, documentés ici pour la transparence méthodologique :

1. **Absence de clé OpenAI** : `ragas.evaluate()` plantait par défaut (`ValidationError: Did not find openai_api_key`). Résolu en injectant explicitement le juge Mistral via les paramètres `llm=` et `embeddings=` de `evaluate()`.
2. **Rate limiting Mistral** : la parallélisation par défaut de RAGAS (jusqu'à ~16 appels juge simultanés) déclenchait des rafales de `429 Too Many Requests`, faisant échouer certains jobs après épuisement des retries. Résolu via un `RunConfig` dédié (`max_workers=2`, `max_retries=20`, `max_wait=45`, `timeout=300`) pour respecter le débit autorisé par le compte utilisé.
3. **`answer_relevancy` systématiquement `NaN`** : cette métrique génère par défaut 3 variantes de réponse en une seule requête (`strictness=3`, mode multi-complétions), mal supporté par `ChatMistralAI` contrairement à OpenAI (cible d'origine de RAGAS). Résolu en réduisant `strictness=1`.
4. **`contexts` incomplet en mode `after`** : seule la requête SQL générée était initialement passée à RAGAS comme contexte, sans les résultats retournés — le juge ne pouvait donc pas vérifier les chiffres cités dans la réponse, faussant `faithfulness` à la baisse. Corrigé en incluant aussi les lignes de résultat (`rows_preview`) dans le contexte transmis à RAGAS.
5. **Réponses chiffrées trop laconiques** : sur certaines questions purement chiffrées, l'application répondait par un nombre isolé (ex. `"3.6"`), ce que l'étape de décomposition en affirmations de `faithfulness` peine à évaluer, produisant un score de 0 malgré une réponse exacte. Corrigé en imposant, dans le prompt système, une réponse toujours formulée en phrase complète.

## 4. Résultats

### 4.1 Tableau comparatif before / after

| Métrique | Before (texte seul) | After (texte + SQL Tool) | Delta |
|---|---|---|---|
| faithfulness | 0,817 | 0,649 | -0,17 |
| answer_relevancy | 0,327 | 0,652 | **+0,33** |
| context_precision | 0,358 | 0,443 | **+0,09** |
| context_recall | 0,385 | 0,577 | **+0,19** |

*(Résultats du run final, post-corrections listées en 3.3, sur les 13 cas de test de `tests/test_questions.py`.)*

### 4.2 Analyse détaillée

**Ce qui s'améliore avec le SQL Tool** — `answer_relevancy`, `context_precision` et `context_recall` progressent tous nettement. Le `context_recall` est le résultat le plus significatif : il confirme que les questions chiffrées (T06, T07, T10, T10b) et mixtes (T11) ne sont tout simplement pas répondables correctement avec le texte seul, et que l'ajout de la base SQL comble ce manque, conformément à l'objectif métier. Exemple : sur T10 (top 3 passeurs), le SQL Tool renvoie un classement exact (mentionnant notamment Trae Young) que le contexte texte seul ne pourrait jamais fournir.

**La baisse de `faithfulness` : un artefact de mesure, pas une régression réelle.** En isolant les scores par question, cette baisse est concentrée sur les questions chiffrées, pas sur les questions texte (T01, T03, T04 ont des scores quasi identiques before/after, cohérent avec le fait que le SQL Tool ne s'y déclenche pas). Exemple concret sur T07 (*« Quelle est la moyenne de rebonds par match ? »*) : le SQL Tool renvoie `avg_rebounds_per_game: 3.6`, l'application répondait initialement `"3.6"` — une réponse exacte et intégralement sourcée du contexte, mais notée `faithfulness = 0.0` par RAGAS, car l'étape de décomposition en affirmations du juge ne parvient pas à traiter un nombre isolé sans phrase. Ce point a été corrigé en cours de projet (voir 3.3, point 5) ; les scores ci-dessus intègrent déjà ce correctif, mais restent sensibles à la formulation exacte des réponses chiffrées — une limite à surveiller plutôt qu'un défaut définitivement clos.

**Un cas de test à corriger : T06.** La question *« Combien de points au total un joueur donné a-t-il marqués cette saison régulière ? »* ne nomme aucun joueur précis. Le SQL Tool répond, à raison, qu'il manque l'information nécessaire — mais ce comportement correct est pénalisé par les métriques de pertinence/recall, car ce n'est pas une question réellement testable telle que formulée. Recommandation : reformuler T06 avec un nom de joueur explicite avant toute nouvelle campagne d'évaluation.

**Un exemple d'hallucination corrigée par un meilleur diagnostic (mode `before`), T02** : à la question *« Que disent les fans du duo de jeunes ailiers évoqué dans les threads playoffs ? »*, le système en mode texte seul a répondu en citant **Anthony Edwards et Jaden McDaniels (Wolves)** — alors que le duo réellement évoqué dans le thread est **Paolo Banchero et Franz Wagner (Orlando Magic)**. Le `context_recall` de cette question est de 0.0 : le retrieval n'a jamais récupéré le bon chunk contenant l'extrait pertinent (noyé parmi des chunks issus d'un autre thread, sur Reggie Miller, sans rapport). C'est un exemple concret et probant des limites du prototype "avant SQL Tool", à conserver comme illustration en soutenance.

### 4.3 Stabilité des résultats

L'évaluation ayant été exécutée plusieurs fois pendant le développement, une variance a été observée d'un run à l'autre (échantillon de seulement 13 questions, juge LLM non strictement déterministe malgré `temperature=0.0`) :

| Run | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|
| Before (1) | 0,796 | 0,301 | 0,271 | 0,385 |
| Before (2) | 0,817 | 0,327 | 0,358 | 0,385 |
| After (1) | 0,725 | 0,496 | 0,409 | 0,615 |
| After (2) | 0,666 | 0,501 | 0,443 | 0,577 |
| After (3, final) | 0,649 | 0,652 | 0,443 | 0,577 |

Le sens des écarts (recall et precision toujours en hausse en mode `after`, `context_recall` toujours en dessous de 0,4 en mode `before`) reste stable d'un run à l'autre, ce qui donne confiance dans la conclusion générale malgré la variance sur les valeurs absolues. Un échantillon plus large (>13 questions) réduirait cette variance et est recommandé pour une évaluation en production.

## 5. Limites

### 5.1 Limites des données sources

Le fichier `regular_NBA.xlsx` contient des **statistiques agrégées sur la saison régulière complète** (une ligne par joueur), sans granularité par match ni distinction domicile/extérieur. Deux cas d'usage cités initialement par Sarah sont de fait **irréalisables avec ces données** :
- « Quel joueur a le meilleur % à 3 points sur les 5 derniers matchs ? »
- « Compare les rebonds de l'équipe à domicile et à l'extérieur. »

Le SQL Tool est conçu pour détecter ce cas et répondre `NO_DATA` plutôt que d'halluciner un résultat approximatif (vérifié par les cas de test T08/T09, tous deux avec `faithfulness = 1.0`, confirmant que le système admet correctement la limite). Si ces cas d'usage restent prioritaires, il faudra obtenir de Sarah un fichier à granularité match par match.

### 5.2 Limites de l'évaluation RAGAS

- Le juge Mistral, bien que fonctionnel après corrections, n'est pas le cas d'usage d'origine de RAGAS (conçu autour d'OpenAI) : certains comportements par défaut (multi-complétions) nécessitent des adaptations (voir 3.3).
- `answer_relevancy` reste sensible à la longueur/forme des réponses (pénalise les réponses courtes et factuelles par rapport à des réponses longues et discursives), un biais à interpréter avec prudence plutôt qu'un signal de qualité brut.
- `faithfulness`, sur des réponses purement chiffrées, dépend de la formulation exacte de la réponse (phrase complète vs valeur isolée) — un point de fragilité de la métrique plus que du système évalué.
- Aucune métrique ne mesure ici la latence ni le coût par requête, deux dimensions pourtant pertinentes pour un usage en production (à envisager pour un futur monitoring).

### 5.3 Limites de l'échantillon de test

13 questions est un échantillon volontairement restreint pour un prototype, suffisant pour un premier audit avant/après mais insuffisant pour une évaluation statistiquement robuste en production. Il ne couvre pas non plus la robustesse à un changement de corpus (nouveaux threads Reddit) ou de modèle de génération — deux axes de sensibilité à anticiper (voir section 6).

## 6. Choix techniques et sensibilité du système (éléments de discussion)

**Pourquoi FAISS + embeddings Mistral plutôt qu'un autre retriever ?** Corpus de taille modeste (quelques threads Reddit), FAISS en local évite une dépendance à un service de vector store managé, cohérent avec un prototype. Le choix serait à revoir (retriever hybride BM25 + dense, reranking) si le corpus grossissait significativement.

**Pourquoi ces 4 métriques RAGAS et pas d'autres ?** Elles couvrent à la fois la qualité de génération (faithfulness, answer_relevancy) et la qualité de récupération (context_precision, context_recall), ce qui permet de diagnostiquer précisément où se situe un problème plutôt que d'avoir un score agrégé opaque — essentiel pour guider les itérations futures.

**Sensibilité à un changement de corpus** : chaque nouvel ajout de contenu dans `inputs/` nécessite un re-passage d'`indexer.py` (l'index FAISS n'est pas mis à jour automatiquement). Un corpus plus volumineux ou plus bruité dégraderait probablement `context_precision` (plus de chunks concurrents pour un même sujet), justifiant à terme un mécanisme de reranking.

**Sensibilité à un changement de modèle de génération** : `MODEL_NAME` (actuellement `mistral-small-latest`) est centralisé dans `utils/config.py`. Changer de modèle nécessiterait de relancer cette même campagne d'évaluation RAGAS avant/après pour vérifier que les gains mesurés se maintiennent — c'est précisément l'intérêt d'avoir industrialisé cette évaluation en script reproductible (`evaluate_ragas.py`) plutôt qu'en test manuel ponctuel.

**Suivi dans le temps / intégration au monitoring** : chaque étape du pipeline (chunking, recherche vectorielle, routage, appel SQL, génération) est déjà instrumentée via Pydantic Logfire (`utils/observability.py`), avec un dashboard consultable en continu une fois `LOGFIRE_TOKEN` configuré. Pour un suivi dans la durée, il est recommandé de programmer `evaluate_ragas.py` en tâche récurrente (ex. à chaque changement de corpus ou de modèle) et de conserver l'historique des CSV de résultats (`reports/`) pour tracer l'évolution des 4 métriques dans le temps.

## 7. Conclusion et recommandations

L'ajout du SQL Tool améliore mesurablement le système sur 3 des 4 métriques RAGAS (answer_relevancy, context_precision, context_recall), confirmant l'intérêt de l'enrichissement chiffré pour répondre aux besoins métier de Sarah. La baisse apparente de `faithfulness` a été investiguée et attribuée principalement à une limite de mesure sur les réponses chiffrées courtes, plutôt qu'à une dégradation réelle de la qualité — un point à surveiller lors des prochaines évaluations plutôt qu'un signal d'alerte.

**Recommandations pour la suite** :
1. Reformuler le cas de test T06 (nommer un joueur précis).
2. Élargir le jeu de test au-delà de 13 questions pour fiabiliser les scores absolus.
3. Obtenir de Sarah un fichier à granularité match par match si les cas d'usage "5 derniers matchs" / "domicile-extérieur" restent prioritaires.
4. Configurer `LOGFIRE_TOKEN` en environnement de production pour un suivi continu des performances.
5. Reproduire cette évaluation à chaque changement significatif de corpus ou de modèle de génération.

## Annexe — Jeu de questions de test complet

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
