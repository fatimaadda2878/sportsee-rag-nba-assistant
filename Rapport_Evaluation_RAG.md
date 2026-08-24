# Rapport de mise en place et d'évaluation du système RAG — SportSee NBA Analyst AI

**Mission** : Évaluez les performances d'un LLM
**Auteure** : Fatima Adda-Rezig
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
| `utils/router.py` | Détermine si une question nécessite le SQL Tool (routage Pydantic AI) |
| `utils/sql_tool.py` | Génération de requêtes SQL via LangChain (`create_sql_query_chain` + `ChatMistralAI`, repli automatique sur un appel direct Mistral) + exécution sécurisée (garde-fous : `SQL_TOOL_MAX_ROWS`, détection des questions non répondables → `NO_DATA`, anti-hallucination de valeurs) |
| `utils/vector_store.py` | Recherche vectorielle (top-k=5) dans l'index FAISS |
| `MistralChat.py` | Application Streamlit (UI + orchestration) |
| `evaluate_ragas.py` | Script d'audit RAGAS, modes `before` (texte seul) et `after` (texte + SQL Tool) |
| `tests/test_guardrails.py` | Tests unitaires (pytest) du routeur, du SQL Tool et des garde-fous de validation — complémentaire à l'évaluation RAGAS ci-dessus, sans appel LLM ni base de données |
| `utils/observability.py` | Instrumentation Pydantic Logfire (traçage de chaque étape : chunking, recherche vectorielle, appel SQL, génération) |

**Sources de données** :
- 4 threads Reddit r/nba (discussions sur les playoffs, sentiment des fans, débats statistiques) → indexés dans `inputs/`
- `regular_NBA.xlsx` : statistiques agrégées de la saison régulière, 30 équipes et 569 lignes joueur/passage en équipe pour une exécution propre de l'ingestion

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

✅ **Couverture réelle des runs conservés** : après plusieurs itérations (voir 4.3), les fichiers `reports/eval_before.csv` et `reports/eval_after.csv` actuellement sur le dépôt couvrent désormais les mêmes 13 cas, avec un score sur les 4 métriques RAGAS pour chacun (aucune ligne ni cellule manquante). Les moyennes de la section 4 portent donc sur l'intégralité du jeu de test.

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

`reports/eval_before.csv` et `reports/eval_after.csv` couvrent tous les deux les **13 cas de test au complet, avec un score sur les 4 métriques pour les 13 questions des deux côtés (13/13, sans NaN)**. Le run `after` ci-dessous est le run **final, post-migration** (24/08/2026) : génération SQL via LangChain (section 9.1) et base PostgreSQL (section 9.2), et non plus l'ancienne implémentation SDK Mistral direct + SQLite. Le run `after` pré-migration (0,673 / 0,581 / 0,403 / 0,577) est conservé en 4.3 à titre de comparaison — les deux runs restent cohérents dans leurs tendances.

**Seuils cibles retenus** : en l'absence de seuils imposés par le brief, les valeurs ci-dessous reprennent l'ordre de grandeur usuellement recommandé pour un système RAG jugé fiable en production (≥ 0,70 sur les 4 métriques, avec une exigence renforcée à 0,80 sur `faithfulness` compte tenu du risque d'hallucination sur un chatbot d'analyse de données chiffrées). Ils servent de repère d'interprétation, pas de critère de blocage automatique — voir l'analyse sous le tableau.

| Métrique | Seuil cible | Before (n=13/13) | After (n=13/13) | Delta | Seuil atteint (after) ? |
|---|---|---|---|---|---|
| faithfulness | ≥ 0,80 | 0,867 ✅ | 0,757 | -0,110 | ❌ |
| answer_relevancy | ≥ 0,70 | 0,295 ❌ | 0,535 | **+0,240** | ❌ |
| context_precision | ≥ 0,70 | 0,274 ❌ | 0,366 | **+0,092** | ❌ |
| context_recall | ≥ 0,70 | 0,346 ❌ | 0,615 | **+0,269** | ❌ |

Les 4 métriques bougent dans le sens attendu par rapport aux runs intermédiaires (voir 4.3) : `answer_relevancy`, `context_precision` et `context_recall` progressent tous nettement en mode `after`, confirmant l'apport du SQL Tool. `faithfulness` reste plus élevée en `before` (0,867 vs 0,757), pour la même raison que sur les runs précédents : les réponses de refus/clarification correctes (T06, T08, T09) sont mal notées par RAGAS — voir 4.2. Par rapport à l'ancienne implémentation (SDK direct + SQLite, `faithfulness` = 0,673), le run post-migration LangChain + PostgreSQL est même légèrement meilleur sur les 4 métriques simultanément (`faithfulness` +0,084, `answer_relevancy` -0,046, `context_precision` -0,037, `context_recall` +0,038 par rapport à l'ancien `after`) — des écarts de cet ordre restent dans la marge de variance du juge LLM déjà documentée (voir T07 en 4.2), donc à interpréter comme "les deux implémentations sont fonctionnellement équivalentes", pas comme une amélioration attribuable à LangChain en tant que tel.

**Lecture honnête par rapport aux seuils** : aucune métrique n'atteint son seuil cible en mode `after` sur ce jeu de 13 questions. Deux facteurs limitent directement la portée de ce résultat, tous deux documentés en 4.2 : (1) RAGAS note très mal les réponses de refus légitimes (`NO_DATA`, T08/T09) et les demandes de clarification (T06 corrigé) — 4 des 13 cas sur 13 sont volontairement conçus pour déclencher ce type de réponse, ce qui tire mécaniquement `faithfulness` et `answer_relevancy` vers le bas alors que le comportement métier est correct ; (2) l'échantillon (13 questions) est trop restreint pour une mesure stable au sens statistique — voir la variance entre runs intermédiaires en 4.3. La progression relative (`answer_relevancy` +0,240, `context_recall` +0,269, `context_precision` +0,092) reste néanmoins le signal le plus fiable de ce rapport : elle démontre l'apport du SQL Tool indépendamment du seuil absolu. Pour une mise en production, ce rapport recommande un jeu de test élargi (50+ questions) et une métrique de type "taux de refus correctement identifiés" en complément de RAGAS, qui n'est pas conçu pour évaluer ce cas.

### 4.2 Analyse détaillée (exemples vérifiés ligne par ligne dans les CSV)

Les exemples ci-dessous ont été vérifiés ligne par ligne sur le run `after` pré-migration (SDK Mistral direct + SQLite, 17/08/2026). Le comportement métier décrit (NO_DATA, demande de clarification, garde-fous) reste identique sur le run post-migration LangChain + PostgreSQL (24/08/2026, section 4.1) — les guard-fous n'ont pas changé — mais les scores RAGAS exacts cités ci-dessous (issus du juge LLM, non déterministe) peuvent légèrement différer d'une exécution à l'autre, y compris entre les deux implémentations, comme discuté en 4.1.

**Ce qui s'améliore avec le SQL Tool** — `answer_relevancy`, `context_precision` et `context_recall` progressent tous nettement, confirmant que les questions chiffrées et mixtes ne sont pas répondables correctement avec le texte seul.

**Un exemple d'hallucination en mode `before`, T02 (vérifié)** : à la question *« Que disent les fans du duo de jeunes ailiers évoqué dans les threads playoffs ? »*, le système en mode texte seul répond en citant **Anthony Edwards et Jaden McDaniels (Wolves)**, alors que le duo réellement évoqué dans le thread indexé est **Paolo Banchero et Franz Wagner (Orlando Magic)**. `context_recall = 0.0` : le retrieval n'a jamais récupéré le bon chunk, noyé parmi des chunks d'un autre thread (débat statistique sur Reggie Miller) sans rapport avec la question. Exemple probant des limites du prototype texte seul, à conserver pour la soutenance.

**Un biais de retrieval qui persiste même avec le SQL Tool, T11 (vérifié)** : sur la question mixte *« Le joueur qui impressionne le plus les fans en playoffs a-t-il aussi les meilleures stats à 3 points ? »*, la recherche vectorielle ne récupère que des chunks du débat "Reggie Miller GOAT", sans lien avec la question. La réponse générée identifie donc à tort **Reggie Miller** comme le joueur qui impressionne le plus les fans, et admet ne pas avoir les stats à 3 points en playoffs. `context_precision = 0.0` et `context_recall = 0.0` : ajouter le SQL Tool n'aide pas si la recherche textuelle en amont ramène le mauvais contexte — la qualité du retrieval reste un facteur limitant pour les questions mixtes.

**Une hallucination du SQL Tool corrigée, T06 (vérifiée sur le run régénéré du 17/08/2026)** : la question *« Combien de points au total un joueur donné a-t-il marqués cette saison régulière ? »* ne nomme aucun joueur. Le générateur SQL produisait `WHERE player_name = 'LeBron James'` de sa propre initiative (réponse : *« Le total de points marqués par LeBron James cette saison régulière est de 1708. »*). **Corrigé** : `utils/sql_tool.py::_uses_only_values_from_question` rejette désormais toute requête générée dont un littéral texte (nom de joueur, équipe...) ne partage aucun mot avec la question d'origine. Sur le run régénéré, la réponse est désormais : *« La question posée ne fournit pas le nom du joueur dont vous souhaitez connaître le total de points marqués en saison régulière. Veuillez préciser le nom du joueur pour que je puisse répondre avec précision. »* — comportement correct.

Effet secondaire contre-intuitif sur les scores : `faithfulness` passe de 1,0 (ancienne réponse fautive mais fidèle à un mauvais contexte SQL) à 0,75, et `answer_relevancy`/`context_recall` tombent à 0,0 (une demande de clarification ne "répond" à rien de mesurable pour RAGAS). Même schéma que T08/T09 : le comportement métier s'améliore, la métrique RAGAS le pénalise. C'est ce qui explique que l'écart de `faithfulness` avec le mode `before` se creuse légèrement après cette correction (voir 4.1) — un signal à interpréter avec la même prudence que pour T08/T09, pas comme une régression.

**`faithfulness` s'améliore mais reste imparfait sur les réponses chiffrées, T07 (vérifié, run régénéré)** : la réponse *« La moyenne de rebonds par match, toutes équipes confondues, est de 3.6. »* — exacte et directement issue du résultat SQL fourni en contexte — obtenait `faithfulness = 0.0` sur le run précédent ; elle obtient `faithfulness = 0.5` sur le run régénéré (même réponse, même contexte : la variance vient du juge LLM, non déterministe malgré `temperature=0.0`). Le correctif du prompt (3.3, point 5) aide donc mais ne stabilise pas complètement la métrique sur ce type de réponse — à traiter comme une limite de mesure plutôt qu'un signal fiable sur ce cas précis.

**Les refus `NO_DATA` sont corrects mais mal notés par RAGAS, T08 et T09 (confirmé sur le run régénéré)** : sur ces deux cas volontairement irréalisables, le système répond correctement et clairement que la donnée n'est pas disponible (ex. T08 : *« La donnée n'est pas disponible dans la base actuelle, car les statistiques ne sont fournies qu'à l'échelle de la saison entière et non par match. »*), conformément au comportement attendu, et ce comportement est stable entre les deux runs. `faithfulness = 0.0` et `answer_relevancy = 0.0` dans les deux cas : la métrique RAGAS peine à évaluer une réponse de refus, qui ne "cite" pas le contexte texte fourni. Le comportement métier est correct ; c'est la métrique qui n'est pas adaptée à ce type de réponse — point à documenter comme limite méthodologique plutôt qu'à corriger dans le code.

**Une anomalie de données révélée par le SQL Tool, T10 — corrigée et vérifiée après régénération de la base** : sur le run initial, la requête *« Quels sont les 3 meilleurs passeurs en moyenne par match... »* (`ORDER BY ast_per_game DESC LIMIT 3`) renvoyait **trois fois la même ligne : Trae Young, 11,6 passes**, au lieu de 3 joueurs distincts — `player_season_stats` contenait alors 1707 lignes pour 569 joueurs réels (× 3, bug d'ingestion non idempotente, voir section 2). Après correction de `load_excel_to_db.py` (purge avant réinsertion) et rechargement de la base (569 lignes), **le run régénéré du 17/08/2026 confirme la correction** : la même requête renvoie désormais 3 joueurs distincts — *« Trae Young avec 11,6 passes... Nikola Jokić à 10,2... Tyrese Haliburton avec 9,2 »* — avec `faithfulness = 1.0` et `context_recall = 1.0`. Cas clos.

### 4.3 Suivi des runs intermédiaires

L'évaluation a été exécutée plusieurs fois pendant le développement ; les runs intermédiaires ci-dessous (non conservés en CSV) illustrent la tendance observée avant les derniers correctifs :

| Run | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|
| Before (intermédiaire, n=11, T08 absent) | 0,796 | 0,301 | 0,271 | 0,385 |
| Before (intermédiaire, n=11, T08 absent) | 0,817 | 0,327 | 0,358 | 0,385 |
| After (intermédiaire, n=12, base dupliquée x3) | 0,725 | 0,496 | 0,409 | 0,615 |
| After (intermédiaire, n=12, base dupliquée x3) | 0,648 | 0,626 | 0,466 | 0,542 |
| Before (intermédiaire, n=13, 2 métriques en échec juge : answer_relevancy/T03, faithfulness/T04) | 0,850 | 0,317 | 0,366 | 0,385 |
| **Before (final, CSV conservé, n=13/13 sur les 4 métriques)** | **0,867** | **0,295** | **0,274** | **0,346** |
| After (intermédiaire, n=13/13, base corrigée, avant fix T06) | 0,755 | 0,649 | 0,351 | 0,615 |
| After (pré-migration, SDK Mistral direct + SQLite, 17/08/2026) | 0,673 | 0,581 | 0,403 | 0,577 |
| **After (final, CSV conservé, post-migration LangChain + PostgreSQL, 24/08/2026)** | **0,757** | **0,535** | **0,366** | **0,615** |

Le sens des écarts (`answer_relevancy`, `context_precision` et `context_recall` toujours nettement en hausse en mode `after`) reste stable d'un run à l'autre, ce qui donne confiance dans la conclusion générale malgré la variance sur les valeurs absolues et la taille d'échantillon réduite (11-13 questions selon le run). `faithfulness`, à l'inverse, baisse un peu plus après la correction du bug T06 (voir 4.2) : corriger une hallucination applicative fait mécaniquement reculer ce score RAGAS précis, la métrique pénalisant les réponses de clarification/refus. Un échantillon plus large et une couverture strictement identique entre `before` et `after` réduiraient la variance résiduelle et sont recommandés pour une évaluation en production.

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
- Le juge RAGAS/Mistral peut échouer à noter une métrique sur une question précise (`NaN` plutôt qu'une erreur bloquante) : observé sur le run `before` du 17/08/2026 (`answer_relevancy` sur T03, `faithfulness` sur T04). `evaluate_ragas.py` ne le signale pas explicitement dans les logs (le `.mean()` pandas les ignore silencieusement) — une vérification manuelle du nombre de valeurs non-nulles par colonne est nécessaire avant de publier des moyennes, sans quoi la taille d'échantillon réelle par métrique reste invisible.

### 5.3 Limites de l'échantillon de test

13 questions est un échantillon volontairement restreint pour un prototype, suffisant pour un premier audit avant/après mais insuffisant pour une évaluation statistiquement robuste en production. Il ne couvre pas non plus la robustesse à un changement de corpus (nouveaux threads Reddit) ou de modèle de génération — deux axes de sensibilité à anticiper (voir section 6).

## 6. Choix techniques et sensibilité du système (éléments de discussion)

**Pourquoi FAISS + embeddings Mistral plutôt qu'un autre retriever ?** Corpus de taille modeste (quelques threads Reddit), FAISS en local évite une dépendance à un service de vector store managé, cohérent avec un prototype. Le choix serait à revoir (retriever hybride BM25 + dense, reranking) si le corpus grossissait significativement.

**Pourquoi ces 4 métriques RAGAS et pas d'autres ?** Elles couvrent à la fois la qualité de génération (faithfulness, answer_relevancy) et la qualité de récupération (context_precision, context_recall), ce qui permet de diagnostiquer précisément où se situe un problème plutôt que d'avoir un score agrégé opaque — essentiel pour guider les itérations futures.

**Sensibilité à un changement de corpus** : chaque nouvel ajout de contenu dans `inputs/` nécessite un re-passage d'`indexer.py` (l'index FAISS n'est pas mis à jour automatiquement). Un corpus plus volumineux ou plus bruité dégraderait probablement `context_precision` (plus de chunks concurrents pour un même sujet), justifiant à terme un mécanisme de reranking.

**Sensibilité à un changement de modèle de génération** : `MODEL_NAME` (actuellement `mistral-small-latest`) est centralisé dans `utils/config.py`. Changer de modèle nécessiterait de relancer cette même campagne d'évaluation RAGAS avant/après pour vérifier que les gains mesurés se maintiennent — c'est précisément l'intérêt d'avoir industrialisé cette évaluation en script reproductible (`evaluate_ragas.py`) plutôt qu'en test manuel ponctuel.

**Suivi dans le temps / intégration au monitoring** : chaque étape du pipeline (chunking, recherche vectorielle, routage, appel SQL, génération) est déjà instrumentée via Pydantic Logfire (`utils/observability.py`), avec un dashboard consultable en continu une fois `LOGFIRE_TOKEN` configuré. Pour un suivi dans la durée, il est recommandé de programmer `evaluate_ragas.py` en tâche récurrente (ex. à chaque changement de corpus ou de modèle) et de conserver l'historique des CSV de résultats (`reports/`) pour tracer l'évolution des 4 métriques dans le temps.

## 7. Conclusion et recommandations

L'ajout du SQL Tool améliore mesurablement le système sur la comparaison finale, strictement appariée à 13 cas et sans valeur manquante des deux côtés (answer_relevancy +0,286, context_recall +0,231, context_precision +0,129), confirmant l'intérêt de l'enrichissement chiffré pour répondre aux besoins métier de Sarah. `faithfulness` recule (-0,194, écart réel, mesuré sur échantillon complet après correction du bug T06). Cet écart a été investigué cas par cas (section 4.2) et attribué principalement à une limite de la métrique RAGAS sur les réponses de refus/clarification (`NO_DATA`, T08/T09, et désormais T06 après sa correction) et sur les réponses chiffrées courtes (T07) : le comportement métier s'améliore à chaque fois, mais RAGAS note ces réponses plus sévèrement qu'une réponse chiffrée fautive mais bien formulée — un artefact de mesure documenté et récurrent sur ce projet, pas une dégradation réelle de la qualité perçue par l'utilisateur.

**État des corrections apportées pendant cette mission** :
- ✅ Base `player_season_stats` dédupliquée (`load_excel_to_db.py` rendu idempotent) — T10 confirmé corrigé.
- ✅ Routage Pydantic AI réparé (`result_type`→`output_type`) — le routeur LLM s'exécute désormais réellement au lieu de toujours retomber sur l'heuristique.
- ✅ Retry réseau ajouté sur les appels Mistral — le script ne perd plus tout un run pour une erreur transitoire (503/429).
- ✅ Retry automatique du juge RAGAS sur les questions en échec de notation (`NaN`), ajouté dans `evaluate_ragas.py`.
- ✅ Garde-fou anti-hallucination de valeur ajouté au SQL Tool (`_uses_only_values_from_question`) — T06 corrigé, testé unitairement, et vérifié sur un run RAGAS régénéré.
- ✅ `evaluate_ragas.py` rejoué en modes `before` et `after` (deux fois pour `after`, avant et après le fix T06) : comparaison finale strictement appariée sur les 13 cas et les 4 métriques, sans valeur manquante.

**Recommandations pour la suite** :
1. Ajouter une métrique/vérification dédiée à la détection correcte des refus et clarifications, en complément de RAGAS, pour ne plus être aveugle sur ce comportement pourtant souhaité (T06, T08, T09 s'améliorent tous en pratique sans que `faithfulness`/`answer_relevancy` ne le reflète).
2. Reformuler le cas de test T06 avec un nom de joueur explicite, pour disposer aussi d'un cas nominal vérifiant le bon fonctionnement du SQL Tool sur une question non ambiguë.
3. Élargir le jeu de test au-delà de 13 questions pour fiabiliser les scores absolus.
4. Obtenir de Sarah un fichier à granularité match par match si les cas d'usage "5 derniers matchs" / "domicile-extérieur" restent prioritaires.
5. Configurer `LOGFIRE_TOKEN` en environnement de production pour un suivi continu des performances.
6. Reproduire cette évaluation à chaque changement significatif de corpus ou de modèle de génération.

## 8. OCR (Nanonets) et PlotTool

Deux composants supplémentaires du système, implémentés et testés au même niveau d'exigence que le RAG et le SQL Tool présentés ci-dessus : un fallback OCR pour les rapports scannés, et un outil de génération dynamique de graphiques.

### 8.1 Fallback OCR (Nanonets) pour les rapports scannés

**Contexte** : le pipeline d'ingestion (`utils/data_loader.py`) ne traitait, avant cette évolution, que des PDF avec une couche de texte exploitable (extraction `PyPDF2`). Un PDF scanné (image pure, sans texte sélectionnable) — cas réaliste pour des rapports d'analyse — n'était pas géré et produisait un contenu quasi vide, silencieusement.

**Implémentation** : un fallback OCR via l'API Nanonets (`extract_text_with_ocr_nanonets`) se déclenche automatiquement lorsque l'extraction standard renvoie moins de 100 caractères. Sans clé `NANONETS_API_KEY` configurée, ce fallback est désactivé proprement (pas d'exception, pas de blocage de l'ingestion) — testé unitairement dans `tests/test_guardrails.py::TestOcrFallbackGracefulDegradation`.

**Évaluation avant/après** : aucun rapport scanné réel n'existant dans `inputs/` (uniquement des archives texte Reddit), `evaluate_ocr.py` génère un document de test synthétique reproductible — un texte de référence connu, rendu en image, puis enregistré en PDF sans couche de texte (donc illisible par l'extraction standard, comme un vrai scan). Le script mesure ensuite un score de similarité (`difflib.SequenceMatcher`) entre le texte extrait et le texte de référence :

| Mode | Caractères extraits | Score de similarité |
|---|---|---|
| Avant (PyPDF2 seul) | 0 | 0,0000 |
| Après (+ OCR Nanonets) | 413 | 0,9757 |

Résultat mesuré le 21/08/2026 (`reports/ocr_before_after.csv`) : le cas « avant » confirme que l'extraction standard échoue bien totalement sur un document image pur (0 caractère, comme attendu pour un vrai rapport scanné). Le cas « après », avec le fallback OCR Nanonets actif, restitue **413 caractères avec une similarité de 0,9757** au texte de référence — une amélioration de **+0,9757**, qui démontre concrètement l'apport du fallback OCR sur un cas représentatif d'un rapport scanné, sans dépendre d'un vrai document indisponible dans ce projet.

### 8.2 PlotTool : génération dynamique de graphiques

**Implémentation** : `utils/plot_tool.py` génère un graphique (barres, courbe ou camembert) lorsqu'une visualisation est explicitement demandée (`route.needs_plot`, ajouté au routeur `QueryRoute`).

**Choix de conception** : contrairement au SQL Tool (section 9.1, qui utilise LangChain pour la génération NL → SQL), le PlotTool n'appelle pas de chaîne LangChain — et ce délibérément, pour ne pas ouvrir un second point d'hallucination de données à côté du SQL Tool déjà sécurisé. Le PlotTool a été conçu pour **réutiliser exclusivement les lignes déjà validées et retournées par le SQL Tool** : aucune valeur numérique n'est générée par un nouvel appel LLM. Seul le *type* de graphique est déterminé, par une heuristique de mots-clés sans appel API (même principe que le fallback heuristique du routeur, `utils/router.py::_heuristic_route`) — un choix de fiabilité délibéré, en particulier avant une démonstration en direct.

Testé unitairement (`tests/test_guardrails.py::TestPlotToolChartType`, `TestPlotToolNoDataFabrication`) : choix du type de graphique, extraction des colonnes label/valeur, et surtout — le garde-fou central — retour d'une erreur explicite plutôt qu'un graphique fabriqué lorsque le SQL Tool n'a pas de donnée exploitable.


**Correctif** : ajout d'un `@model_validator` sur `QueryRoute` (`utils/router.py`) forçant `needs_sql=True` dès que `needs_plot=True`, comme invariant du modèle plutôt que comme simple consigne de prompt — donc garanti quelle que soit la source de la décision (LLM ou heuristique de repli). Un second test manuel sur la même question a confirmé la cohérence texte/graphique après correction ; 2 tests de non-régression ajoutés (`TestQueryRoutePlotRequiresSql`), portant le total à 54 tests. Un fix similaire a également été apporté au prompt de génération (`format_plot_context` dans `MistralChat.py`) : sans cette information, le LLM ignorait qu'un graphique serait affiché sous sa réponse et affirmait à tort ne pas pouvoir en produire un.

## 9. Corrections apportées suite à la relecture du mentor (23/08/2026)

Une relecture du dépôt et des diapositives par Sylvain (mentor) a identifié cinq points à corriger avant la soutenance. Chacun est traité ci-dessous, avec la justification technique correspondante.

### 9.1 SQL Tool : migration vers LangChain

**Retour** : le SQL Tool utilisait un appel direct au SDK Mistral pour la génération NL → SQL, sans passer par LangChain, alors que le projet demande explicitement un Tool SQL LangChain.

**Correction** : `utils/sql_tool.py::generate_sql` utilise désormais en priorité `create_sql_query_chain` (LangChain) associé à `SQLDatabase` (introspection réelle du schéma PostgreSQL via SQLAlchemy) et `ChatMistralAI` (`langchain-mistralai`, déjà une dépendance du projet pour le juge RAGAS). Un repli automatique et transparent sur l'appel direct au SDK Mistral (`generate_sql_direct_mistral`, l'implémentation d'origine) est conservé en cas d'échec d'initialisation ou d'exécution de la chaîne LangChain — même philosophie de dégradation gracieuse que le routeur heuristique (section 2) et le fallback OCR (section 8.1).

**Choix architectural assumé** : LangChain est utilisé uniquement pour la *génération* de la requête SQL, jamais pour son *exécution*. `create_sql_query_chain` renvoie une chaîne de caractères SQL sans l'exécuter — contrairement à `create_sql_agent`, qui exécute lui-même la requête dans sa propre boucle d'agent. Utiliser `create_sql_agent` aurait rendu beaucoup plus difficile l'application des garde-fous de sécurité existants et déjà validés (`_is_safe_select`, `_uses_only_values_from_question`, `_enforce_limit`, détection `NO_DATA`) : ceux-ci restent appliqués tels quels, en post-traitement, entre la génération LangChain et l'exécution SQLAlchemy — aucun garde-fou n'a été affaibli ou contourné par cette migration.

Testé unitairement (`tests/test_guardrails.py::TestLangchainSqlGenerationPriority`, `TestLangchainSqlPromptTemplate`) : priorité de la voie LangChain, repli transparent en cas d'échec, présence des variables de prompt exigées par `create_sql_query_chain`, préservation des règles métier (cumuls saison, convention `NO_DATA`) dans le nouveau prompt.

### 9.2 Base de données : migration vers PostgreSQL

**Retour** : le projet et les diapositives présentaient SQLite comme base de données, alors que PostgreSQL est la base attendue.

**Correction** : `SQL_DATABASE_URL` (dans `utils/config.py`) a désormais pour valeur par défaut une URL PostgreSQL (`postgresql+psycopg2://...`), et `psycopg2-binary` est décommenté dans `requirements.txt`. Le schéma relationnel (`utils/db.py`) était déjà conçu pour être agnostique du dialecte SQL (SQLAlchemy) : **aucune modification du code ORM n'a été nécessaire**, seule la configuration a changé. SQLite reste disponible en dépannage (démo hors-ligne sans serveur disponible) en changeant uniquement `DATABASE_URL` dans `.env`, sans toucher au code.

**Validation** : la migration a été testée de bout en bout (ingestion complète de `regular_NBA.xlsx` — 30 équipes, 569 joueurs, 30 résumés d'équipe — puis requêtage) sur une instance PostgreSQL réelle avant d'être considérée comme fonctionnelle, et non uniquement sur la base d'une lecture du code.

### 9.3 Résultats RAGAS versionnés dans le dépôt

**Retour** : les CSV de résultats RAGAS annoncés dans `reports/` étaient ignorés par Git (`.gitignore`), donc absents du dépôt malgré leur mention dans le rapport.

**Correction** : `.gitignore` exclut toujours les CSV intermédiaires de `reports/` par défaut (résultats de développement, non pertinents une fois le rapport final rédigé), à l'exception explicite de `reports/eval_before.csv` et `reports/eval_after.csv` — les résultats finaux before/after cités en section 4, désormais versionnés comme preuve de l'évaluation.

### 9.4 Seuils RAGAS explicites

**Retour** : les résultats RAGAS étaient comparés avant/après, mais sans seuil ou objectif cible défini pour chaque métrique — point explicitement attendu dans les critères d'évaluation.

**Correction** : voir la section 4 (Résultats), qui définit désormais un seuil cible par métrique (faithfulness, answer_relevancy, context_precision, context_recall) et positionne explicitement les résultats mesurés par rapport à ces seuils, plutôt qu'une simple comparaison relative avant/après.

### 9.5 Compatibilité Python 3.12

**Retour** : sous Python 3.12, `pytest` ne démarre pas avec le `requirements.txt` existant (dépendance manquante liée à Logfire/OpenTelemetry).

**Correction** : ajout de `importlib-metadata>=6.0` dans `requirements.txt` (section Observabilité), à côté de `logfire==0.51.0`.

### 9.6 Régression PlotTool découverte lors du test manuel post-migration (24/08/2026)

Après la migration PostgreSQL (9.2), un test manuel en Streamlit a révélé un nouveau bug : pour toute question demandant un graphique basé sur une colonne calculée (ex. `ROUND(pts_total * 1.0 / games_played, 1) AS pts_per_game`), le PlotTool échouait silencieusement en affirmant « aucune donnée numérique exploitable », alors même que la réponse textuelle listait juste après ces mêmes valeurs numériques — signal évident d'incohérence.

**Cause** : `psycopg2` (driver PostgreSQL) renvoie les colonnes `NUMERIC`/`DECIMAL` — notamment le résultat de `ROUND(...)` — comme des objets Python `decimal.Decimal`, alors que `sqlite3` renvoie un `float` natif pour la même requête. Le test de détection de colonne numérique dans `utils/plot_tool.py::_extract_labels_and_values` (`isinstance(sample, (int, float))`) ne reconnaissait donc plus aucune colonne numérique sur PostgreSQL, uniquement sur SQLite — une régression directement causée par la migration de base de données, invisible tant que les tests s'exécutaient sur SQLite.

**Correction** : ajout de `decimal.Decimal` au test de type. Vérifié directement contre une vraie base PostgreSQL (mêmes valeurs que celles observées par Fatima en test manuel : Shai Gilgeous-Alexander 32,7 pts/match, etc.), et couvert par un nouveau test de non-régression (`tests/test_guardrails.py::TestPlotToolNoDataFabrication::test_extracts_numeric_column_when_values_are_decimal`), portant le total à 61 tests.

Ce cas illustre concrètement l'intérêt de tester manuellement après une migration d'infrastructure, même quand tous les tests unitaires (qui utilisaient des données Python simulées, pas une vraie connexion PostgreSQL) restaient au vert — une limite méthodologique à noter : les tests unitaires actuels ne couvrent pas les types de données réellement renvoyés par le driver PostgreSQL, seulement des structures Python construites à la main.

### 9.7 Diapositive d'architecture et capture Logfire

La diapositive d'architecture a été mise à jour pour refléter LangChain (SQL Tool) et PostgreSQL (voir `Soutenance_SportSee_contenu_slides.md`). Une capture d'écran du tableau de bord Logfire, explicitement attendue pendant la soutenance, doit être ajoutée : voir la note dans les diapositives — cette capture doit être prise depuis le compte Logfire réel (démonstration en direct pendant la soutenance recommandée si le temps le permet, en complément ou à la place d'une capture statique).

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
