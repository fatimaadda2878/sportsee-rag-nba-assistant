# tests/test_questions.py
"""
Jeu de questions métier catégorisées, utilisé par evaluate_ragas.py pour
auditer le prototype (Étape 1 : avant SQL Tool) puis pour mesurer l'impact de
l'enrichissement chiffré (Étape 3 : après SQL Tool).

Catégories (voir utils.schemas.TestCategory) :
    simple_texte       - question qualitative directe, réponse dans un seul chunk
    complexe_texte     - question qualitative nécessitant de croiser plusieurs sources
    bruite_texte       - question formulée de façon ambiguë / avec fautes / hors contexte partiel
    simple_chiffre     - agrégation simple sur la base SQL (ex: total points d'un joueur)
    complexe_chiffre   - agrégation multicritère (ex: meilleur % à 3pts de la saison, min tentatives)
    mixte_texte_chiffre- nécessite à la fois le contexte texte ET le SQL Tool
    hors_perimetre     - question hors sujet (doit être refusée/gérée proprement)

IMPORTANT : les `ground_truth` ci-dessous sont des réponses de référence
GÉNÉRIQUES écrites pour illustrer la structure attendue par RAGAS. Elles ne
sont pas garanties exactes tant que evaluate_ragas.py n'a pas été exécuté
pour de vrai sur les vraies archives Reddit et la vraie base NBA (voir
README, section limites). À affiner par Sarah/l'équipe métier une fois les
données réellement chargées et l'audit réel lancé.

⚠️ T08 et T09 testent volontairement des questions IRRÉALISABLES avec le
fichier Excel réel (aucune donnée par match, aucun home/away — voir README
"Limites des données sources") : leur ground_truth attend un aveu explicite
de la limite (NO_DATA), pas un chiffre inventé. Ne pas les "corriger" pour
qu'elles passent artificiellement sans revalider d'abord si Sarah peut
fournir des données à la granularité match.
"""
from utils.schemas import EvalTestCase, TestCategory

TEST_CASES: list[EvalTestCase] = [
    # --- Simple texte ---
    EvalTestCase(
        id="T01",
        category=TestCategory.SIMPLE_TEXTE,
        question="Quelles équipes des playoffs ont le plus impressionné les fans récemment ?",
        ground_truth=(
            "D'après le thread r/nba, plusieurs équipes sont citées positivement : le Orlando Magic "
            "(Paolo Banchero, Franz Wagner) pour avoir poussé les Celtics, champions en titre, jusqu'à la "
            "limite malgré un tir d'équipe famélique ; les Minnesota Timberwolves (menés par Anthony "
            "Edwards) pour leur niveau des deux côtés du terrain face aux Lakers ; les Detroit Pistons "
            "(Cade Cunningham) pour leur progression ; et les Indiana Pacers (Tyrese Haliburton, Pascal "
            "Siakam) pour avoir surpris tout le monde en playoffs."
        ),
        requires_sql=False,
        notes="Basé sur le thread Reddit 'Who are teams in the playoffs that have impressed you?' (Reddit 2.txt).",
    ),
    EvalTestCase(
        id="T02",
        category=TestCategory.SIMPLE_TEXTE,
        question="Que disent les fans du duo de jeunes ailiers évoqué dans les threads playoffs ?",
        ground_truth=(
            "Le duo évoqué est Paolo Banchero et Franz Wagner (Orlando Magic) : les fans soulignent leur "
            "solidité défensive et leur capacité à créer des tirs malgré une adresse parfois inconstante, "
            "en notant que le reste de l'effectif du Magic manque de shooteurs et d'un vrai meneur pour "
            "passer un cap."
        ),
        requires_sql=False,
        notes="Basé sur le thread Reddit 'Who are teams in the playoffs that have impressed you?' (Reddit 2.txt).",
    ),

    # --- Complexe texte ---
    EvalTestCase(
        id="T03",
        category=TestCategory.COMPLEXE_TEXTE,
        question="En croisant les différents threads Reddit, quel est le sentiment général sur le niveau de compétitivité des playoffs cette année ?",
        ground_truth=(
            "Le sentiment est partagé : d'un côté, des équipes jugées outsiders sont saluées pour leur "
            "combativité (Orlando Magic, Minnesota Timberwolves, Detroit Pistons, Indiana Pacers, voir "
            "T01) ; de l'autre, un thread débat du fait que la finale Oklahoma City Thunder - Indiana "
            "Pacers, pourtant opposant statistiquement les deux meilleures équipes des playoffs, est "
            "perçue par certains médias comme un potentiel 'snoozefest' à cause du manque de superstars "
            "connues du grand public - un avis que beaucoup de commentateurs Reddit contestent, défendant "
            "le style de jeu rapide et la défense d'élite des deux équipes."
        ),
        requires_sql=False,
        notes="Nécessite d'agréger l'info de plusieurs chunks/documents Reddit distincts (Reddit 2.txt + Reddit 3.txt).",
    ),

    # --- Bruité ---
    EvalTestCase(
        id="T04",
        category=TestCategory.BRUITE_TEXTE,
        question="dites moi ce ke les gens pensen des playoff cet année svp??",
        ground_truth=(
            "Réponse équivalente à T01/T03 malgré les fautes et le langage informel : citer notamment "
            "Orlando Magic, Minnesota Timberwolves, Detroit Pistons et Indiana Pacers comme équipes ayant "
            "impressionné, et le débat autour de la finale OKC Thunder - Indiana Pacers."
        ),
        requires_sql=False,
        notes="Teste la robustesse au bruit orthographique/informel.",
    ),
    EvalTestCase(
        id="T05",
        category=TestCategory.BRUITE_TEXTE,
        question="Et sinon, niveau ambiance, c'est comment cette saison par rapport à la boxe ?",
        ground_truth=(
            "Question hors périmètre basket (mélange avec un autre sport) : l'assistant doit indiquer qu'il "
            "ne dispose pas d'information sur la boxe plutôt que d'inventer une réponse."
        ),
        requires_sql=False,
        notes="Détecte les hallucinations sur du hors-sujet partiel.",
    ),

    # --- Simple chiffré (nécessite SQL Tool, Étape 2/3) ---
    EvalTestCase(
        id="T06",
        category=TestCategory.SIMPLE_CHIFFRE,
        question="Combien de points au total un joueur donné a-t-il marqués cette saison régulière ?",
        ground_truth="Valeur exacte = SUM(pts_total) filtré par player_name (agrégé si plusieurs équipes dans la saison), retournée par le SQL Tool.",
        requires_sql=True,
        notes="pts_total est déjà un cumul saison dans la base (pas de SUM sur plusieurs lignes 'match').",
    ),
    EvalTestCase(
        id="T07",
        category=TestCategory.SIMPLE_CHIFFRE,
        question="Quelle est la moyenne de rebonds par match, toutes équipes confondues ?",
        ground_truth="Valeur exacte = AVG(reb / games_played) sur player_season_stats, retournée par le SQL Tool.",
        requires_sql=True,
    ),

    # --- Complexe chiffré ---
    EvalTestCase(
        id="T08",
        category=TestCategory.COMPLEXE_CHIFFRE,
        question="Quel joueur a le meilleur pourcentage de réussite à 3 points sur les 5 derniers matchs ?",
        ground_truth=(
            "L'assistant doit indiquer que cette donnée n'est PAS disponible : la base ne contient "
            "aucune donnée par match (statistiques agrégées sur la saison entière uniquement), donc "
            "impossible de calculer un pourcentage sur '5 derniers matchs'. Le SQL Tool doit répondre "
            "NO_DATA plutôt que d'inventer un résultat approximatif."
        ),
        requires_sql=True,
        notes=(
            "Cas d'usage cité explicitement par Sarah dans le brief initial, mais IRRÉALISABLE avec le "
            "fichier Excel fourni (vérifié le 11/08/2026, aucune colonne date/match). Teste que le "
            "système admet la limite plutôt que d'halluciner — voir README 'Limites des données sources'."
        ),
    ),
    EvalTestCase(
        id="T09",
        category=TestCategory.COMPLEXE_CHIFFRE,
        question="Compare les statistiques de rebonds de l'équipe à domicile et à l'extérieur.",
        ground_truth=(
            "L'assistant doit indiquer que cette donnée n'est PAS disponible : aucune colonne "
            "domicile/extérieur n'existe dans la base. Le SQL Tool doit répondre NO_DATA."
        ),
        requires_sql=True,
        notes="Cas d'usage cité explicitement par Sarah, également irréalisable avec les données actuelles.",
    ),
    EvalTestCase(
        id="T10",
        category=TestCategory.COMPLEXE_CHIFFRE,
        question="Quels sont les 3 meilleurs passeurs en moyenne par match cette saison (au moins 10 matchs joués) ?",
        ground_truth="Top 3 par (ast / games_played) DESC, filtré sur games_played >= 10, retourné par le SQL Tool.",
        requires_sql=True,
        notes="Reformulation réalisable de l'intention initiale de T10 (assists), adaptée aux vraies données saison.",
    ),
    EvalTestCase(
        id="T10b",
        category=TestCategory.COMPLEXE_CHIFFRE,
        question="Quel joueur a le meilleur pourcentage à 3 points cette saison, avec au moins 50 tentatives ?",
        ground_truth="Le joueur avec tp_pct le plus élevé parmi ceux ayant tpa >= 50, retourné par le SQL Tool.",
        requires_sql=True,
        notes="Version réalisable (saison entière au lieu de '5 derniers matchs') du cas d'usage T08.",
    ),

    # --- Mixte texte + chiffré ---
    EvalTestCase(
        id="T11",
        category=TestCategory.MIXTE_TEXTE_CHIFFRE,
        question="Le joueur qui impressionne le plus les fans en playoffs a-t-il aussi les meilleures stats à 3 points ?",
        ground_truth=(
            "Réponse combinant le sentiment qualitatif des threads Reddit (Anthony Edwards - Minnesota "
            "Timberwolves - et Paolo Banchero - Orlando Magic - ressortent comme les joueurs qui "
            "impressionnent le plus, voir T01/T02) et le classement réel du pourcentage à 3 points "
            "(tp_pct, via le SQL Tool sur player_season_stats), en signalant explicitement si le(s) "
            "joueur(s) cité(s) figure(nt) ou non en tête du classement tp_pct réel."
        ),
        requires_sql=True,
        notes="Teste la synthèse conjointe texte + SQL par l'agent.",
    ),

    # --- Hors périmètre ---
    EvalTestCase(
        id="T12",
        category=TestCategory.HORS_PERIMETRE,
        question="Peux-tu me donner la recette d'un cookie au chocolat ?",
        ground_truth="L'assistant doit décliner poliment, hors périmètre NBA.",
        requires_sql=False,
    ),
]


def get_test_cases(category: TestCategory | None = None) -> list[EvalTestCase]:
    """Filtre optionnellement le jeu de tests par catégorie."""
    if category is None:
        return TEST_CASES
    return [tc for tc in TEST_CASES if tc.category == category]
