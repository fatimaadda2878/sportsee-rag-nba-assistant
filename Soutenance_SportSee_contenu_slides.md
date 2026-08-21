# Support de soutenance — SportSee NBA Analyst AI
### Contenu prêt à transférer dans PowerPoint / Google Slides — 10 slides (+1 optionnelle : 8bis), ~12 minutes

> Mon sandbox de génération de fichiers (.pptx) est indisponible pendant cette session. Ce document contient tout le contenu, slide par slide, avec les notes orateur — à copier-coller directement. Dès que l'environnement technique est de nouveau disponible, je peux te générer le vrai fichier `.pptx` à partir de ce même contenu.

**Palette suggérée** : navy (`1E2761`) / ice blue (`CADCFC`) / blanc — sobre, professionnel, cohérent avec un sujet data/IA.

---

## Slide 1 — Titre

**SportSee — NBA Analyst AI**
Un assistant conversationnel hybride RAG + SQL, évalué objectivement avec RAGAS

*Mission : Évaluez les performances d'un LLM*
Fatima Adda — Août 2026

**Visuel suggéré** : fond navy uni, titre en grand, logo/silhouette basket en filigrane si tu en as un.

**Notes orateur** :
"Bonjour, je vais vous présenter SportSee, un assistant conversationnel destiné aux coachs et analystes NBA, et surtout la démarche d'évaluation objective que j'ai menée pour mesurer l'apport réel d'un enrichissement SQL à un système RAG classique."

---

## Slide 2 — Contexte et mission

**Le besoin de Sarah (product owner)**
Un assistant capable de répondre à deux types de questions :
- **Qualitatives** : archives texte (discussions Reddit r/nba, rapports)
- **Quantitatives** : statistiques joueurs/équipes (fichier `regular_NBA.xlsx`)

**Objectif double**
1. Construire un prototype combinant recherche vectorielle (RAG) et interrogation SQL
2. **Évaluer objectivement** l'apport du SQL Tool avec le framework RAGAS (before / after)

**Visuel suggéré** : deux icônes côte à côte (bulle de discussion + graphique statistique) reliées par un "+".

**Notes orateur** :
"Le point de départ, c'est un constat simple : un RAG purement textuel sait bien répondre à des questions qualitatives, mais échoue structurellement sur les questions chiffrées précises. L'enjeu de la mission était de le vérifier, pas de le supposer — d'où la démarche d'évaluation comparative avant/après."

---

## Slide 3 — Architecture du système

**Pipeline d'une question**
1. Question utilisateur (Streamlit)
2. **Routeur Pydantic AI** → la question nécessite-t-elle des données chiffrées ?
3. **Recherche vectorielle FAISS** (archives texte) et/ou **SQL Tool** (NL → SQL sécurisé, SQLite)
4. **Génération Mistral** — réponse fondée strictement sur le contexte récupéré
5. Observabilité : chaque étape tracée avec **Pydantic Logfire**

**Visuel suggéré** : diagramme de flux simple (déjà présent dans le README, à reproduire visuellement) — question → routeur → deux branches (texte / SQL) → génération → réponse.

**Notes orateur** :
"Le routeur, construit avec Pydantic AI, décide automatiquement si une question a besoin du contexte texte, du SQL Tool, ou des deux. Le SQL Tool ne génère jamais de requête destructrice : validation Pydantic en entrée, SELECT uniquement, limite de lignes, et surtout un mécanisme NO_DATA pour refuser plutôt qu'inventer quand la donnée n'existe pas."

---

## Slide 4 — Méthodologie d'évaluation

**13 questions de test, 7 catégories**
| Catégorie | Exemple |
|---|---|
| Texte simple / complexe | "Quelles équipes ont le plus impressionné les fans ?" |
| Texte bruité | Fautes, langage familier |
| Chiffré simple / complexe | "Top 3 passeurs de la saison ?" |
| Mixte texte + chiffre | Croise sentiment Reddit et stats réelles |
| Hors périmètre | Question non-NBA (doit être déclinée) |

**4 métriques RAGAS** : faithfulness, answer_relevancy, context_precision, context_recall
Juge : Mistral (`ChatMistralAI`), pas OpenAI (adapté spécifiquement au projet)

**Visuel suggéré** : petit tableau des 7 catégories avec icônes, ou liste à puces avec icônes distinctes par catégorie.

**Notes orateur** :
"J'ai volontairement inclus deux questions irréalisables — pas de données match par match dans le fichier source — pour vérifier que le système sait dire 'je ne sais pas' plutôt que d'halluciner un chiffre. C'est un point que je détaillerai."

---

## Slide 5 — Résultats chiffrés

**Comparaison finale before / after (13 questions, appariées, sans donnée manquante)**

| Métrique | Before (texte seul) | After (+ SQL Tool) | Évolution |
|---|---|---|---|
| Faithfulness | **0,867** | 0,673 | -0,194 |
| Answer Relevancy | 0,295 | **0,581** | **+0,286** |
| Context Precision | 0,274 | **0,403** | **+0,129** |
| Context Recall | 0,346 | **0,577** | **+0,231** |

**Visuel suggéré** : graphique en barres groupées (before/after côte à côte pour chaque métrique) — natif PowerPoint/Google Slides, pas une image. Mets en évidence les trois évolutions positives (Answer Relevancy, Context Precision, Context Recall) avec une couleur accent.

**Notes orateur** :
"Le SQL Tool améliore nettement 3 métriques sur 4. La pertinence des réponses (+0,29) et le rappel du contexte (+0,23) progressent fortement : le système trouve et utilise mieux l'information nécessaire. La faithfulness recule, j'y reviens dans deux slides — ce n'est pas ce que ça semble être au premier regard."

---

## Slide 6 — Ce qui s'améliore concrètement

**Exemple 1 — Avant le SQL Tool, une hallucination (T02)**
Question : "Que disent les fans du duo de jeunes ailiers évoqué en playoffs ?"
- Réponse générée (texte seul) : *Anthony Edwards et Jaden McDaniels*
- Réalité du thread indexé : *Paolo Banchero et Franz Wagner*
- → Mauvais chunk récupéré, noyé dans un thread sans rapport (`context_recall = 0`)

**Exemple 2 — Avec le SQL Tool, une réponse exacte (T10)**
Question : "Top 3 passeurs de la saison ?"
- Réponse : *Trae Young (11,6), Nikola Jokić (10,2), Tyrese Haliburton (9,2)*
- Donnée impossible à obtenir avec le texte seul

**Visuel suggéré** : deux colonnes côte à côte (❌ avant / ✅ après), avec les citations en italique.

**Notes orateur** :
"Ces deux exemples illustrent concrètement pourquoi les métriques bougent : le texte seul peut halluciner en toute confiance quand le retrieval se trompe de document, alors que le SQL Tool donne une réponse vérifiable, traçable, directement issue de la base."

---

## Slide 7 — La baisse de faithfulness expliquée

**Pas une régression de qualité — une limite de la métrique**

- **T08/T09** (cas volontairement irréalisables) : le système répond correctement *"donnée non disponible"* → comportement attendu et correct
  - Mais RAGAS note `faithfulness = 0` car un refus ne "cite" pas de contexte à évaluer
- **T06** : le SQL Tool demande désormais une clarification plutôt que d'inventer un joueur non précisé — mais ce comportement correct fait chuter le score (1,0 → 0,75, `answer_relevancy` à 0) — **une correction de comportement fait baisser le score**, preuve que la baisse globale n'est pas un signal de qualité fiable
- **T07** (réponse chiffrée courte) : réponse exacte et sourcée, faithfulness instable d'un run à l'autre selon le juge LLM, non déterministe

**→ Le comportement métier s'améliore à chaque fois ; c'est l'outil de mesure qui n'est pas conçu pour évaluer des refus/clarifications.**

**Visuel suggéré** : un encadré "⚠️ Limite méthodologique identifiée" avec icône loupe/warning.

**Notes orateur** :
"C'est le point le plus important de mon analyse critique : une baisse de score n'est pas automatiquement une baisse de qualité. J'ai vérifié chaque cas ligne par ligne dans les CSV plutôt que de me fier à la moyenne brute, et ça change complètement l'interprétation."

---

## Slide 8 — Fiabilité du système : garde-fous, tests, observabilité

**Sécurité du SQL Tool**
- Requêtes SELECT uniquement, rejet DML/DDL
- Limite de lignes retournées, détection d'injection basique
- Mécanisme `NO_DATA` explicite plutôt qu'une hallucination
- Vérification que toute valeur citée (nom de joueur, équipe) provient bien de la question posée

**34 tests unitaires (pytest)** — routeur, SQL Tool, validation Pydantic, 100% verts, sans appel API ni base de données

**Observabilité en continu (Pydantic Logfire)** — chaque étape du pipeline est tracée (recherche vectorielle, appel SQL, génération), dashboard consultable en temps réel

**Visuel suggéré** : trois colonnes ou trois icônes en ligne (bouclier / checklist / radar), chacune avec un court label — sécurité, tests, observabilité.

**Notes orateur** :
"Au-delà de l'évaluation RAGAS, qui mesure la qualité des réponses, j'ai construit une couche de fiabilité indépendante : des garde-fous qui empêchent le SQL Tool de sortir de son périmètre, des tests unitaires qui vérifient que ces garde-fous continuent de fonctionner à chaque modification du code, et une observabilité en continu pour détecter tout problème en production, pas seulement au moment de l'évaluation."

---

## Slide 8bis — Aller plus loin : OCR (Nanonets) et PlotTool

*(Optionnelle si le temps est serré — sinon 1 min max, pour montrer que le travail sur ces deux points n'a pas été perdu)*

**OCR — remplacement d'EasyOCR par Nanonets OCR**
- Fallback automatique quand un PDF n'a pas de couche de texte (rapport scanné)
- Évaluation avant/après reproductible : `evaluate_ocr.py`, sur un document de test synthétique (texte de référence connu, rendu en image, sans OCR le texte extrait est **vide** — 0 caractère, similarité 0,00)
- Avec le fallback OCR Nanonets actif : **413 caractères restitués, similarité de 0,9757** avec le texte de référence — amélioration de **+0,98**

**PlotTool — génération dynamique de graphiques**
- Le chatbot peut désormais produire un graphique (barres/courbe/camembert) sur demande explicite ("montre un graphique de...")
- Garde-fou important : le PlotTool ne réutilise QUE les données déjà validées par le SQL Tool — il ne peut pas inventer une valeur, seul le type de graphique est choisi automatiquement

**Visuel suggéré** : deux mini-captures d'écran (un graphique généré en direct + le score OCR avant/après).

**Notes orateur** :
"Deux fonctionnalités demandées en complément du périmètre principal : un OCR de secours pour les rapports scannés, et un outil de visualisation. J'ai gardé le même principe de sécurité que pour le SQL Tool : aucun de ces deux ajouts ne peut inventer une donnée — l'OCR échoue proprement sans clé API, et le PlotTool ne trace que des chiffres déjà vérifiés par le SQL Tool."

---

## Slide 9 — Limites et pistes d'amélioration

- Échantillon volontairement restreint (13 questions) — à élargir pour des scores statistiquement robustes
- Granularité des données NBA limitée à la saison (pas de match par match, pas de domicile/extérieur)
- `ground_truth` à faire valider par un référent métier (Sarah)
- Coût/latence non mesurés — à ajouter pour un usage en production

**Visuel suggéré** : liste à puces simple, icône "piste/flèche" par item.

**Notes orateur** :
"Je préfère assumer ces limites explicitement plutôt que de présenter un score parfait qui ne résisterait pas à un examen approfondi — c'est d'ailleurs toute la démarche de ce rapport."

---

## Slide 10 — Conclusion

**Ce que la mission démontre**
Un RAG purement textuel ne suffit pas pour des questions quantitatives précises — même bien conçu, il hallucine faute de la bonne donnée.

**Ce que l'évaluation objective apporte**
- Une mesure chiffrée, reproductible (`evaluate_ragas.py`), pas une impression
- Une méthode pour distinguer un vrai bug d'une limite d'outil de mesure
- Une architecture hybride (RAG + SQL + routage) directement réutilisable

**Merci — questions ?**

**Visuel suggéré** : fond navy (retour au style du titre), grande phrase de conclusion centrée.

**Notes orateur** :
"Pour conclure : le SQL Tool comble un vrai manque du RAG textuel seul, et je peux le prouver avec des chiffres plutôt qu'une affirmation — c'était l'objectif de cette mission. Je suis prête à répondre à vos questions."
