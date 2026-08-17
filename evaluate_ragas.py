# evaluate_ragas.py
"""
Script d'évaluation automatisé basé sur RAGAS.

Deux modes :
    --mode before  : évalue le prototype tel quel (recherche vectorielle texte
                      uniquement), pour établir la baseline (Étape 1).
    --mode after   : évalue le système enrichi (routage + SQL Tool + texte),
                      pour mesurer l'impact de l'Étape 2 (Étape 3).

Métriques RAGAS calculées :
    - faithfulness       : la réponse est-elle fidèle au contexte fourni (pas d'hallucination) ?
    - answer_relevancy    : la réponse répond-elle bien à la question posée ?
    - context_precision   : le contexte récupéré est-il pertinent (peu de bruit) ?
    - context_recall      : le contexte récupéré couvre-t-il la ground_truth ?

Sortie : un CSV dans reports/ (une ligne par cas de test + les 4 scores),
utilisable pour construire le tableau comparatif avant/après de l'Étape 3.

⚠️ Prérequis pour une exécution réelle (non faite ici, voir README - sandbox
indisponible au moment de la rédaction) :
    - MISTRAL_API_KEY valide dans .env
    - Index Faiss construit (`python indexer.py`)
    - Base SQL peuplée (`python load_excel_to_db.py`) pour le mode "after"
    - `pip install -r requirements.txt`

Usage :
    python evaluate_ragas.py --mode before --output reports/eval_before.csv
    python evaluate_ragas.py --mode after  --output reports/eval_after.csv
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from datasets import Dataset

from utils.vector_store import VectorStoreManager
from utils.router import route_query
from utils.sql_tool import run_sql_tool
from utils.config import MISTRAL_API_KEY, MODEL_NAME, SEARCH_K
from utils.observability import logfire
from utils.mistral_client import chat_complete
from tests.test_questions import get_test_cases

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("evaluate_ragas")


SYSTEM_PROMPT_TEMPLATE = """Tu es 'NBA Analyst AI'. Réponds STRICTEMENT à partir du contexte fourni.

Réponds TOUJOURS par au moins une phrase complète en français, même pour un
résultat purement chiffré (ex: "La moyenne de rebonds par match est de 3.6."
et non juste "3.6"). Une réponse réduite à un nombre ou un mot isolé n'est
pas acceptable.

--- CONTEXTE TEXTE ---
{text_context}

--- RÉSULTATS CHIFFRÉS ---
{sql_context}

QUESTION: {question}
RÉPONSE:"""


def _format_sql_context(sql_output) -> str:
    if sql_output is None:
        return "Non applicable (mode 'before' ou question non chiffrée)."
    if sql_output.error:
        return f"Erreur SQL: {sql_output.error}"
    if sql_output.row_count == 0:
        return "Aucun résultat."
    lines = [f"SQL: {sql_output.generated_sql}"] + [str(r) for r in sql_output.rows_preview]
    return "\n".join(lines)


def run_pipeline_for_question(question: str, mode: str,
                               vector_store: VectorStoreManager) -> dict:
    """Exécute le pipeline complet (recherche + éventuellement SQL + génération)
    pour une question, et retourne answer/contexts pour RAGAS."""
    with logfire.span("eval_run_pipeline", question=question, mode=mode):
        # --- Contexte texte (toujours, pour comparer équitablement) ---
        search_results = vector_store.search(question, k=SEARCH_K) if vector_store and vector_store.index else []
        contexts = [r["text"] for r in search_results] or ["Aucun contexte trouvé."]
        text_context = "\n\n---\n\n".join(contexts)

        # --- SQL Tool uniquement en mode 'after', si le routeur le juge pertinent ---
        sql_output = None
        if mode == "after":
            route = route_query(question)
            if route.needs_sql:
                sql_output = run_sql_tool(question)
                if sql_output and not sql_output.error and sql_output.row_count > 0:
                    # On ajoute la requête SQL ET les résultats (pas juste la
                    # requête) : RAGAS juge la fidélité de la réponse par
                    # rapport à `contexts`, il faut donc que les valeurs
                    # chiffrées citées dans la réponse y soient visibles,
                    # pas seulement le SQL qui les a produites.
                    contexts.append(_format_sql_context(sql_output))

        sql_context = _format_sql_context(sql_output)

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            text_context=text_context, sql_context=sql_context, question=question
        )
        answer = chat_complete(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )

        return {"answer": answer, "contexts": contexts}


def build_ragas_dataset(mode: str) -> Dataset:
    """Construit le dataset HuggingFace attendu par ragas.evaluate()."""
    if not MISTRAL_API_KEY:
        raise RuntimeError(
            "MISTRAL_API_KEY manquante : impossible d'exécuter le pipeline réel. "
            "Configurez le .env avant de lancer l'évaluation."
        )

    vector_store = VectorStoreManager()

    questions, ground_truths, answers, contexts_list, categories, ids = [], [], [], [], [], []

    for tc in get_test_cases():
        logger.info(f"[{tc.id}] ({tc.category.value}) {tc.question}")
        result = run_pipeline_for_question(tc.question, mode, vector_store)

        ids.append(tc.id)
        categories.append(tc.category.value)
        questions.append(tc.question)
        ground_truths.append(tc.ground_truth)
        answers.append(result["answer"])
        contexts_list.append(result["contexts"])

    return Dataset.from_dict({
        "id": ids,
        "category": categories,
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
        "ground_truth": ground_truths,
    })


def run_evaluation(mode: str, output_path: str) -> pd.DataFrame:
    with logfire.span("run_ragas_evaluation", mode=mode):
        dataset = build_ragas_dataset(mode)

        # Import différé : ragas + ses dépendances (LLM/embeddings judges) ne sont
        # nécessaires qu'ici. Par défaut ragas utilise des modèles OpenAI pour
        # juger les réponses ; ce projet n'a pas de clé OpenAI (uniquement Mistral),
        # on branche donc explicitement un juge Mistral via langchain_mistralai.
        from ragas import evaluate
        from ragas.metrics import faithfulness, context_precision, context_recall
        from ragas.metrics import AnswerRelevancy
        from ragas.run_config import RunConfig
        from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings

        # answer_relevancy par défaut (strictness=3) demande au juge de générer
        # 3 variantes en une seule requête (n=3) pour faire un vote majoritaire.
        # ChatMistralAI (contrairement à OpenAI, cible d'origine de ragas) ne
        # gère pas correctement ce mode multi-complétions, ce qui faisait
        # échouer silencieusement la métrique sur 100% des lignes (NaN partout).
        # strictness=1 : une seule génération, comme les 3 autres métriques.
        answer_relevancy = AnswerRelevancy(strictness=1)

        # mistral-small-latest : nettement plus rapide que mistral-large-latest
        # comme juge (moins critique ici que pour la génération des réponses),
        # ce qui limite le risque de TimeoutError sur un compte à débit limité.
        judge_llm = ChatMistralAI(
            model="mistral-small-latest",
            mistral_api_key=MISTRAL_API_KEY,
            temperature=0.0,
        )
        judge_embeddings = MistralAIEmbeddings(
            model="mistral-embed",
            mistral_api_key=MISTRAL_API_KEY,
        )

        # Le compte Mistral utilisé a une limite stricte de requêtes/seconde.
        # RAGAS lance par défaut ~16 jobs juge en parallèle (nb_questions x
        # nb_métriques), ce qui déclenche une rafale de 429 Too Many Requests
        # et fait échouer certains jobs après épuisement des retries.
        # max_workers=2 : compromis entre débit et respect du rate limit
        # (1 seul était trop lent : ~180s/it, ~2h30 pour les 52 jobs).
        # timeout=180 s'est révélé trop court : avec des rafales de 429, le
        # temps cumulé des retries (jusqu'à max_retries x max_wait) dépassait
        # le timeout du job avant même d'avoir pu réessayer correctement,
        # d'où les TimeoutError résiduels. On relève le timeout et on
        # raccourcit le backoff max pour enchaîner les retries plus vite.
        run_config = RunConfig(max_workers=2, max_retries=20, max_wait=45, timeout=300)
        metric_cols = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

        results = evaluate(
            dataset, metrics=metrics, llm=judge_llm, embeddings=judge_embeddings, run_config=run_config,
        )
        df = results.to_pandas()
        df["id"] = dataset["id"]
        df["category"] = dataset["category"]

        # ⚠️ Le juge RAGAS/Mistral peut échouer à noter une métrique sur une
        # question précise (NaN, sans lever d'exception) même après les
        # retries internes de `RunConfig`. Un `.mean()` sur un DataFrame avec
        # des NaN les ignore silencieusement (taille d'échantillon réduite
        # sans avertissement), ce qui rendait les runs before/after non
        # comparables métrique par métrique (voir Rapport_Evaluation_RAG.md,
        # section 5.2). On ré-exécute `evaluate()` uniquement sur les
        # questions concernées, jusqu'à `_MAX_NAN_RETRY_PASSES` passes, pour
        # tenter de compléter les cellules manquantes avant de figer le CSV.
        _MAX_NAN_RETRY_PASSES = 3
        for attempt in range(1, _MAX_NAN_RETRY_PASSES + 1):
            nan_mask = df[metric_cols].isna().any(axis=1)
            if not nan_mask.any():
                break
            failing_ids = df.loc[nan_mask, "id"].tolist()
            logger.warning(
                f"[{mode}] {len(failing_ids)} question(s) avec au moins une métrique non notée "
                f"(NaN) après passe {attempt}: {failing_ids}. Nouvelle tentative sur ces questions "
                f"uniquement ({attempt}/{_MAX_NAN_RETRY_PASSES})."
            )
            retry_dataset = dataset.filter(lambda row: row["id"] in failing_ids)
            retry_results = evaluate(
                retry_dataset, metrics=metrics, llm=judge_llm, embeddings=judge_embeddings,
                run_config=run_config,
            )
            retry_df = retry_results.to_pandas()
            retry_df["id"] = retry_dataset["id"]
            # Fusion cellule par cellule (id + colonne métrique), pas ligne
            # entière : on ne veut écraser que ce qui était NaN, pas repasser
            # sur des scores déjà obtenus avec succès à la passe précédente.
            retry_by_id = retry_df.set_index("id")
            for idx in df.index[nan_mask]:
                row_id = df.at[idx, "id"]
                if row_id not in retry_by_id.index:
                    continue
                for col in metric_cols:
                    if pd.isna(df.at[idx, col]) and not pd.isna(retry_by_id.at[row_id, col]):
                        df.at[idx, col] = retry_by_id.at[row_id, col]

        remaining_nan_mask = df[metric_cols].isna().any(axis=1)
        if remaining_nan_mask.any():
            still_failing = df.loc[remaining_nan_mask, ["id"] + metric_cols].to_dict(orient="records")
            logger.error(
                f"[{mode}] {int(remaining_nan_mask.sum())} question(s) restent non notées sur au "
                f"moins une métrique après {_MAX_NAN_RETRY_PASSES} tentatives, malgré le retry : "
                f"{still_failing}. Ces cellules resteront vides dans le CSV — la comparaison "
                f"before/after ne sera pas strictement appariée sur 13/13 pour ces métriques."
            )
            logfire.info("ragas_judge_unresolved_nan", mode=mode, failing=still_failing)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        logger.info(f"Résultats sauvegardés dans {output_path}")

        # Moyenne ET taille d'échantillon réelle par métrique (n non-null),
        # affichées explicitement plutôt que de laisser un .mean() silencieux
        # masquer d'éventuelles valeurs manquantes.
        nb_valid = df[metric_cols].notna().sum()
        summary = df[metric_cols].mean()
        summary_lines = "\n".join(
            f"{col}: mean={summary[col]:.4f} (n={int(nb_valid[col])}/{len(df)})" for col in metric_cols
        )
        logger.info(f"--- Scores moyens ({mode}) ---\n{summary_lines}")
        logfire.info(
            "ragas_evaluation_completed", mode=mode,
            **summary.to_dict(), **{f"{c}_n": int(nb_valid[c]) for c in metric_cols},
        )

        return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Évaluation RAGAS du prototype RAG SportSee")
    parser.add_argument("--mode", choices=["before", "after"], required=True,
                         help="'before' = texte seul (Étape 1) | 'after' = texte + SQL Tool (Étape 3)")
    parser.add_argument("--output", type=str, default=None,
                         help="Chemin du CSV de sortie (par défaut reports/eval_<mode>.csv)")
    args = parser.parse_args()

    output = args.output or f"reports/eval_{args.mode}.csv"
    run_evaluation(args.mode, output)
