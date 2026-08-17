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
| `tests/test_guardrails.py` | Tests unitaires (pytest) du routeur, du SQL Tool et des garde-fous de validation — complémentaire à l'évaluation RAGAS ci-dessus, sans appel LLM ni base de données |
| `utils/observability.py` | Instrumentation Pydantic Logfire (traçage de chaque étape : chunking, recherche vectorielle, appel SQL, génération) |

**Sources de données** :
- 4 threads Reddit r/nba (discussions sur les playoffs, sentiment des fans, débats statistiques) → indexés dans `inputs/`
- `regular_NBA.xlsx` : statistiques agrégées de la saison régulière, 30 équipes et 569 lignes joueur/passage en équipe pour une exécution propre de l'ingestion (validé le 11/08/2026)

⚠️ **Bug de duplication détecté et corrigé le 17/08/2026** : `load_excel_to_db.py::load_player_season_stats` ne purgeait pas la table avant réinsertion (contrairement aux deux autres tables). Vérification directe sur la base utilisée pour cette évaluation : `SELECT COUNT(*) FROM player_season_stats` renvoyait **1707** lignes, soit exactement 569 × 3 — la table avait été remplie par 3 exécutions successives du script sans purge. Ce constat éclaire directement l'anomalie relevée sur T10 en section 4.2 (voir ci-dessous). Le script a été corrigé pour vider la table avant chaque rechargement ; **les résultats RAGAS de ce rapport ont été mesurés sur la base non corrigée (1707 lignes)**, une nouvelle campagne après correction est recommandée (voir section 7).

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

⚠️ **Couverture réelle des runs conservés** : les fichiers `reports/eval_before.csv` et `reports/eval_after.csv` actuellement sur le dépôt ne couvrent pas exactement les mêmes 13 cas. `T08` est absent du run `before` (11 cas exploités), et `T10b` est absent des deux runs (12 cas exploités en `after`). Les moyennes de la section 4 sont calculées sur les lignes réellement présentes dans ces CSV, pas sur les 13 cas théoriques — voir section 5.3 pour l'impact sur la comparaison.

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

Moyennes recalculées directement à partir des fichiers `reports/eval_before.csv` (11 cas, `T08` absent) et `reports/eval_after.csv` (12 cas, `T10b` absent) actuellement dans le dépôt :

| Métrique | Before — n=11 | After — n=12 | Delta |
|---|---|---|---|
| faithfulness | 0,783 | 0,648 | -0,135 |
| answer_relevancy | 0,357 | 0,626 | **+0,269** |
| context_precision | 0,405 | 0,466 | **+0,061** |
| context_recall | 0,364 | 0,542 | **+0,178** |

*(Recalcul du 17/08/2026 à partir des CSV existants, tailles d'échantillon before/after non identiques — voir 5.3.)*

### 4.2 Analyse détaillée (exemples vérifiés ligne par ligne dans les CSV)

**Ce qui s'améliore avec le SQL Tool** — `answer_relevancy`, `context_precision` et `context_recall` progressent tous nettement, confirmant que les questions chiffrées et mixtes ne sont pas répondables correctement avec le texte seul.

**Un exemple d'hallucination en mode `before`, T02 (vérifié)** : à la question *« Que disent les fans du duo de jeunes ailiers évoqué dans les threads playoffs ? »*, le système en mode texte seul répond en citant **Anthony Edwards et Jaden McDaniels (Wolves)**, alors que le duo réellement évoqué dans le thread indexé est **Paolo Banchero et Franz Wagner (Orlando Magic)**. `context_recall = 0.0` : le retrieval n'a jamais récupéré le bon chunk, noyé parmi des chunks d'un autre thread (débat statistique sur Reggie Miller) sans rapport avec la question. Exemple probant des limites du prototype texte seul, à conserver pour la soutenance.

**Un biais de retrieval qui persiste même avec le SQL Tool, T11 (vérifié)** : sur la question mixte *« Le joueur qui impressionne le plus les fans en playoffs a-t-il aussi les meilleures stats à 3 points ? »*, la recherche vectorielle ne récupère que des chunks du débat "Reggie Miller GOAT", sans lien avec la question. La réponse générée identifie donc à tort **Reggie Miller** comme le joueur qui impressionne le plus les fans, et admet ne pas avoir les stats à 3 points en playoffs. `context_precision = 0.0` et `context_recall = 0.0` : ajouter le SQL Tool n'aide pas si la recherche textuelle en amont ramène le mauvais contexte — la qualité du retrieval reste un facteur limitant pour les questions mixtes.

**Une hallucination du SQL Tool lui-même, T06 (vérifié)** : la question *« Combien de points au total un joueur donné a-t-il marqués cette saison régulière ? »* ne nomme aucun joueur. Au lieu de renvoyer `NO_DATA` ou de demander une précision, le générateur SQL a produit `WHERE player_name = 'LeBron James'` de sa propre initiative et l'application a répondu avec ce chiffre comme si la question l'avait demandé. C'est un vrai défaut de garde-fou (le SQL Tool devrait détecter l'ambiguïté et refuser plutôt qu'inventer un joueur), cohérent avec le score `context_recall = 0.0` de cette question. **Recommandation : ajouter une vérification explicite dans `sql_tool.py` pour rejeter/signaler les requêtes générées contenant une valeur (nom de joueur, équipe...) non présente dans la question d'origine.**

**`faithfulness` reste à 0 sur les réponses chiffrées même reformulées en phrase complète, T07 (vérifié)** : malgré le correctif imposant une réponse en phrase complète (voir 3.3, point 5), la réponse *« La moyenne de rebonds par match, toutes équipes confondues, est de 3.6. »* — exacte et directement issue du résultat SQL fourni en contexte — obtient tout de même `faithfulness = 0.0`. Le correctif du prompt n'a donc pas suffi à lui seul ; la métrique `faithfulness` de RAGAS reste fragile sur les réponses purement chiffrées sourcées par SQL, à traiter comme une limite de la métrique plutôt qu'un signal fiable sur ce cas précis.

**Les refus `NO_DATA` sont corrects mais mal notés par RAGAS, T08 et T09 (correction d'une erreur du rapport précédent)** : sur ces deux cas volontairement irréalisables, le système répond correctement et clairement que la donnée n'est pas disponible (ex. T08 : *« La donnée n'est pas disponible dans la base actuelle, car les statistiques ne sont fournies qu'à l'échelle de la saison entière et non par match. »*), conformément au comportement attendu. **Contrairement à une version précédente de ce rapport, les scores `faithfulness` mesurés ne sont pas de 1,0 mais de 0,0 pour ces deux cas** : la métrique RAGAS peine à évaluer une réponse de refus, qui ne "cite" pas le contexte texte fourni (puisqu'elle explique une limite de la base plutôt que d'en extraire une information). Le comportement métier est correct ; c'est la métrique qui n'est pas adaptée à ce type de réponse — point à documenter comme limite méthodologique plutôt qu'à corriger dans le code.

**Une anomalie de données révélée par le SQL Tool, T10 (vérifié, cause racine confirmée)** : sur *« Quels sont les 3 meilleurs passeurs en moyenne par match... »*, la requête générée (`ORDER BY ast_per_game DESC LIMIT 3`) renvoie **trois fois la même ligne : Trae Young, 11,6 passes**, au lieu de 3 joueurs distincts. La réponse générée reflète fidèlement ce résultat (*« Trae Young... suivi du même Trae Young... et enfin Trae Young »*), d'où un `faithfulness = 1.0` malgré un résultat manifestement incohérent. **Cause racine confirmée (et non plus supposée)** : `load_excel_to_db.py::load_player_season_stats` n'était pas idempotent (voir section 2, encadré) — la base utilisée pour cette évaluation contenait 1707 lignes dans `player_season_stats` pour 569 joueurs réels (× 3), chaque joueur, dont Trae Young, y étant présent trois fois à l'identique. Ce n'est donc pas une limite du SQL Tool mais un bug d'ingestion, désormais corrigé (purge de la table avant réinsertion). **Recommandation : re-générer la base avec le script corrigé et rejouer T10 avant de considérer ce cas clos.**

### 4.3 Suivi des runs intermédiaires

L'évaluation a été exécutée plusieurs fois pendant le développement ; les runs intermédiaires ci-dessous (non conservés en CSV) illustrent la tendance observée avant les derniers correctifs :

| Run | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|
| Before (intermédiaire 1) | 0,796 | 0,301 | 0,271 | 0,385 |
| After (intermédiaire 1) | 0,725 | 0,496 | 0,409 | 0,615 |
| After (intermédiaire 2) | 0,666 | 0,501 | 0,443 | 0,577 |
| **Before (final, CSV conservé)** | **0,783** | **0,357** | **0,405** | **0,364** |
| **After (final, CSV conservé)** | **0,648** | **0,626** | **0,466** | **0,542** |

Le sens des écarts (`answer_relevancy`, `context_precision` et `context_recall` toujours en hausse en mode `after`) reste stable d'un run à l'autre, ce qui donne confiance dans la conclusion générale malgré la variance sur les valeurs absolues et la taille d'échantillon réduite (11-12 questions selon le run). Un échantillon plus large et une couverture strictement identique entre `before` et `after` réduiraient cette variance et sont recommandés pour une évaluation en production.

## 5. Limites

### 5.1 Limites des données sources

Le fichier `regular_NBA.xlsx` contient des **statistiques agrégées sur la saison régulière complète** (une ligne par joueur), sans granularité par match ni distinction domicile/extérieur. Deux cas d'usage cités initialement par Sarah sont de fait **irréalisables avec ces données** :
- « Quel joueur a le meilleur % à 3 points sur les 5 derniers matchs ? »
- « Compare les rebonds de l'équipe à domicile et à l'extérieur. »

Le SQL Tool est conçu pour détecter ce cas et répondre `NO_DATA` plutôt que d'halluciner un résultat approximatif. Vérifié par les cas de test T08/T09 : le système répond bien par un refus explicite et correct dans les deux cas (voir 4.2), même si la métrique `faithfulness` RAGAS les note à 0,0 (limite de la métrique sur les réponses de refus, pas un défaut du comportement métier). Si ces cas d'usage restent prioritaires, il faudra obtenir de Sarah un fichier à granularité match par match.

### 5.2 Limites de l'évaluation RAGAS

- Le juge Mistral, bien que fonctionnel après corrections, n'est pas le cas d'usage d'origine de RAGAS (conçu autour d'OpenAI) : certains comportements par défaut (multi-complétions) nécessitent des adaptations (voir 3.3).
- `answer_relevancy` reste sensible à la longueur/forme des réponses (pénalise les réponses courtes et factuelles par rapport à des réponses longues et discursives), un biais à interpréter avec prudence plutôt qu'un signal de qualité brut.
- `faithfulness`, sur des réponses purement chiffrées, dépend de la formulation exacte de la réponse (phrase complète vs valeur isolée) — un point de fragilité de la métrique plus que du système évalué.
- Aucune métrique ne mesure ici la latence ni le coût par requête, deux dimensions pourtant pertinentes pour un usage en production (à envisager pour un futur monitoring).

### 5.3 Limites de l'échantillon de test

13 questions est un échantillon volontairement restreint pour un prototype, suffisant pour un premier audit avant/après mais insuffisant pour une évaluation statistiquement robuste en production. Il ne couvre pas non plus la robustesse à un changement de corpus (nouveaux threads Reddit) ou de modèle de génération — deux axes de sensibilité à anticiper (voir section 6).

De plus, la comparaison before/after actuellement disponible n'est **pas strictement appariée** : `T08` (complexe_chiffre, cas `NO_DATA`) est absent du run `before` conservé, et `T10b` (complexe_chiffre) est absent des deux runs. Les moyennes de la section 4.1 portent donc sur 11 questions en `before` et 12 en `after`, pas sur les 13 mêmes questions. La tendance générale (progression de `answer_relevancy`, `context_precision`, `context_recall`) reste cohérente sur les runs intermédiaires disponibles (voir 4.3), mais une comparaison rigoureuse nécessiterait de relancer `evaluate_ragas.py --mode before` et `--mode after` sur exactement les mêmes 13 cas avant toute publication de ces chiffres en production.

## 6. Choix techniques et sensibilité du système (éléments de discussion)

**Pourquoi FAISS + embeddings Mistral plutôt qu'un autre retriever ?** Corpus de taille modeste (quelques threads Reddit), FAISS en local évite une dépendance à un service de vector store managé, cohérent avec un prototype. Le choix serait à revoir (retriever hybride BM25 + dense, reranking) si le corpus grossissait significativement.

**Pourquoi ces 4 métriques RAGAS et pas d'autres ?** Elles couvrent à la fois la qualité de génération (faithfulness, answer_relevancy) et la qualité de récupération (context_precision, context_recall), ce qui permet de diagnostiquer précisément où se situe un problème plutôt que d'avoir un score agrégé opaque — essentiel pour guider les itérations futures.

**Sensibilité à un changement de corpus** : chaque nouvel ajout de contenu dans `inputs/` nécessite un re-passage d'`indexer.py` (l'index FAISS n'est pas mis à jour automatiquement). Un corpus plus volumineux ou plus bruité dégraderait probablement `context_precision` (plus de chunks concurrents pour un même sujet), justifiant à terme un mécanisme de reranking.

**Sensibilité à un changement de modèle de génération** : `MODEL_NAME` (actuellement `mistral-small-latest`) est centralisé dans `utils/config.py`. Changer de modèle nécessiterait de relancer cette même campagne d'évaluation RAGAS avant/après pour vérifier que les gains mesurés se maintiennent — c'est précisément l'intérêt d'avoir industrialisé cette évaluation en script reproductible (`evaluate_ragas.py`) plutôt qu'en test manuel ponctuel.

**Suivi dans le temps / intégration au monitoring** : chaque étape du pipeline (chunking, recherche vectorielle, routage, appel SQL, génération) est déjà instrumentée via Pydantic Logfire (`utils/observability.py`), avec un dashboard consultable en continu une fois `LOGFIRE_TOKEN` configuré. Pour un suivi dans la durée, il est recommandé de programmer `evaluate_ragas.py` en tâche récurrente (ex. à chaque changement de corpus ou de modèle) et de conserver l'historique des CSV de résultats (`reports/`) pour tracer l'évolution des 4 métriques dans le temps.

## 7. Conclusion et recommandations

L'ajout du SQL Tool améliore mesurablement le système sur 3 des 4 métriques RAGAS (answer_relevancy +0,269, context_precision +0,061, context_recall +0,178), confirmant l'intérêt de l'enrichissement chiffré pour répondre aux besoins métier de Sarah. La baisse de `faithfulness` (-0,135) a été investiguée cas par cas (section 4.2) : elle recouvre à la fois une limite de la métrique RAGAS sur les réponses de refus (`NO_DATA`, T08/T09) et sur les réponses chiffrées courtes (T07), un vrai défaut applicatif (le SQL Tool peut halluciner une valeur non demandée, T06), et un bug d'ingestion des données (table `player_season_stats` triplée faute de purge avant réinsertion, à l'origine de l'anomalie T10 — voir section 2). Ce dernier bug étant corrigé après la campagne mesurée ici, **les chiffres de la section 4.1 restent valables comme diagnostic mais devront être rejoués sur une base assainie avant publication finale**.

**Recommandations pour la suite** :
1. Relancer `python load_excel_to_db.py` (script désormais idempotent) pour repartir sur une base `player_season_stats` propre (569 lignes, plus 1707), puis rejouer `evaluate_ragas.py --mode after` pour confirmer que T10 se corrige.
2. Corriger `utils/sql_tool.py` pour rejeter/signaler une requête générée contenant une valeur (nom de joueur, équipe...) absente de la question d'origine (voir T06).
3. Reformuler le cas de test T06 avec un nom de joueur explicite, et aligner strictement la couverture `before`/`after` (actuellement 11 vs 12 cas sur 13, voir 5.3) avant toute nouvelle campagne de mesure.
4. Élargir le jeu de test au-delà de 13 questions pour fiabiliser les scores absolus.
5. Obtenir de Sarah un fichier à granularité match par match si les cas d'usage "5 derniers matchs" / "domicile-extérieur" restent prioritaires.
6. Configurer `LOGFIRE_TOKEN` en environnement de production pour un suivi continu des performances.
7. Reproduire cette évaluation à chaque changement significatif de corpus ou de modèle de génération.

## Annexe — Jeu de questions de test complet

Les 13 cas ci-dessous sont définis dans `tests/test_questions.py`. Seuls `T08` (absent du run `before` conservé) et `T10b` (absent des deux runs conservés) n'apparaissent pas dans les résultats chiffrés de la section 4 — voir 5.3.

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
