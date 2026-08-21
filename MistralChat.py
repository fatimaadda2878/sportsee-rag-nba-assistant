# MistralChat.py (version RAG + SQL Tool)
import streamlit as st
import logging

# --- Importations depuis les modules du projet ---
try:
    from utils.config import (
        MISTRAL_API_KEY, MODEL_NAME, SEARCH_K,
        APP_TITLE, NAME
    )
    from utils.vector_store import VectorStoreManager
    from utils.router import route_query
    from utils.sql_tool import run_sql_tool
    from utils.plot_tool import run_plot_tool
    from utils.observability import logfire
    from utils.mistral_client import chat_complete, MistralClientError
except ImportError as e:
    st.error(f"Erreur d'importation: {e}. Vérifiez la structure de vos dossiers et les fichiers dans 'utils'.")
    st.stop()


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

# --- Configuration de l'API Mistral ---
api_key = MISTRAL_API_KEY
model = MODEL_NAME

if not api_key:
    st.error("Erreur : Clé API Mistral non trouvée (MISTRAL_API_KEY). Veuillez la définir dans le fichier .env.")
    st.stop()


# --- Chargement du Vector Store (mis en cache) ---
@st.cache_resource
def get_vector_store_manager():
    logging.info("Tentative de chargement du VectorStoreManager...")
    try:
        manager = VectorStoreManager()
        if manager.index is None or not manager.document_chunks:
            st.error("L'index vectoriel ou les chunks n'ont pas pu être chargés.")
            st.warning("Assurez-vous d'avoir exécuté 'python indexer.py' après avoir placé vos fichiers dans le dossier 'inputs'.")
            logging.error("Index Faiss ou chunks non trouvés/chargés par VectorStoreManager.")
            return None
        logging.info(f"VectorStoreManager chargé avec succès ({manager.index.ntotal} vecteurs).")
        return manager
    except FileNotFoundError:
        st.error("Fichiers d'index ou de chunks non trouvés.")
        st.warning("Veuillez exécuter 'python indexer.py' pour créer la base de connaissances.")
        logging.error("FileNotFoundError lors de l'init de VectorStoreManager.")
        return None
    except Exception as e:
        st.error(f"Erreur inattendue lors du chargement du VectorStoreManager: {e}")
        logging.exception("Erreur chargement VectorStoreManager")
        return None


vector_store_manager = get_vector_store_manager()

# --- Prompt Système pour RAG (texte + SQL) ---
SYSTEM_PROMPT = f"""Tu es 'NBA Analyst AI', un assistant expert sur la ligue de basketball NBA.
Ta mission est de répondre aux questions des fans en t'appuyant STRICTEMENT sur les informations
fournies ci-dessous (contexte texte et/ou résultats chiffrés). Si une donnée n'est pas présente,
dis-le clairement plutôt que d'inventer un chiffre.

Réponds TOUJOURS par au moins une phrase complète, même pour un résultat purement
chiffré (ex: "La moyenne de rebonds par match est de 3.6." et non juste "3.6").

--- CONTEXTE TEXTE (rapports, archives) ---
{{text_context}}

--- RÉSULTATS CHIFFRÉS (base de données SQL) ---
{{sql_context}}

QUESTION DU FAN:
{{question}}

RÉPONSE DE L'ANALYSTE NBA (cite les chiffres exacts s'ils sont disponibles) :"""


if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": f"Bonjour ! Je suis votre analyste IA pour la {NAME}. Posez-moi vos questions sur les équipes, "
                   f"les joueurs ou les statistiques, et je vous répondrai en me basant sur les données les plus récentes."
    }]


def generer_reponse(prompt_messages: list) -> str:
    """Envoie le prompt (contexte texte + SQL inclus) à l'API Mistral."""
    if not prompt_messages:
        logging.warning("Tentative de génération de réponse avec un prompt vide.")
        return "Je ne peux pas traiter une demande vide."
    with logfire.span("llm_generate_answer"):
        try:
            logging.info(f"Appel à l'API Mistral modèle '{model}' avec {len(prompt_messages)} message(s).")
            content = chat_complete(model=model, messages=prompt_messages, temperature=0.1)
            logging.info("Réponse reçue de l'API Mistral.")
            return content
        except MistralClientError as e:
            st.error(f"Erreur lors de l'appel à l'API Mistral: {e}")
            logging.exception("Erreur API Mistral pendant chat_complete")
            logfire.error("llm_generation_error", error=str(e))
            return "Je suis désolé, une erreur technique m'empêche de répondre. Veuillez réessayer plus tard."


def format_sql_context(sql_output) -> str:
    """Transforme un SQLToolOutput en texte lisible pour le prompt LLM."""
    if sql_output is None:
        return "Aucune requête chiffrée n'a été exécutée pour cette question."
    if sql_output.error:
        if sql_output.error.startswith("Donnée non disponible"):
            return (
                f"{sql_output.error}. Indique clairement à l'utilisateur que cette donnée précise "
                f"n'est pas disponible dans la base actuelle (statistiques agrégées sur la saison "
                f"entière uniquement, pas de détail par match ni domicile/extérieur), sans inventer "
                f"de chiffre. Réponds uniquement à partir du contexte texte si celui-ci est pertinent."
            )
        return f"La requête SQL a échoué ({sql_output.error}). Réponds uniquement à partir du contexte texte si possible."
    if sql_output.row_count == 0:
        return f"Requête exécutée mais aucun résultat trouvé.\nSQL: {sql_output.generated_sql}"

    lines = [f"SQL exécutée: {sql_output.generated_sql}", f"Colonnes: {', '.join(sql_output.columns)}"]
    for row in sql_output.rows_preview:
        lines.append(str(row))
    if sql_output.truncated:
        lines.append("(résultats tronqués — affinez la question pour plus de précision)")
    return "\n".join(lines)


# --- Interface Utilisateur Streamlit ---
st.title(APP_TITLE)
st.caption(f"Assistant virtuel pour {NAME} | Modèle: {model}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

if prompt := st.chat_input(f"Posez votre question sur la {NAME}..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with logfire.span("handle_user_question", question=prompt):

        # === 1. Routage : la question nécessite-t-elle le SQL Tool ? ===
        route = route_query(prompt)
        logging.info(f"Routage: needs_sql={route.needs_sql}, needs_text_context={route.needs_text_context} ({route.reasoning})")

        # === 2. Recherche de contexte texte (si pertinent) ===
        text_context = "Aucun contexte texte recherché pour cette question."
        if route.needs_text_context and vector_store_manager is not None:
            try:
                search_results = vector_store_manager.search(prompt, k=SEARCH_K)
                if search_results:
                    text_context = "\n\n---\n\n".join([
                        f"Source: {res['metadata'].get('source', 'Inconnue')} (Score: {res['score']:.1f}%)\nContenu: {res['text']}"
                        for res in search_results
                    ])
                else:
                    text_context = "Aucune information pertinente trouvée dans la base de connaissances pour cette question."
            except Exception as e:
                st.error(f"Une erreur est survenue lors de la recherche d'informations pertinentes: {e}")
                logging.exception("Erreur pendant vector_store_manager.search")
                text_context = "La recherche de contexte texte a échoué."
        elif vector_store_manager is None:
            text_context = "Le service de recherche de connaissances n'est pas disponible."

        # === 3. Appel du SQL Tool (si pertinent) ===
        sql_output = None
        if route.needs_sql:
            try:
                sql_output = run_sql_tool(prompt)
            except Exception as e:
                st.error(f"Une erreur est survenue lors de l'interrogation de la base de données: {e}")
                logging.exception("Erreur pendant run_sql_tool")

        sql_context = format_sql_context(sql_output)

        # === 3bis. Génération du graphique (si demandé explicitement) ===
        # Réutilise sql_output déjà calculé : pas de second appel SQL, et le
        # PlotTool ne peut représenter que des données déjà validées par le
        # SQL Tool (voir utils/plot_tool.py).
        plot_output = None
        if route.needs_plot:
            try:
                plot_output = run_plot_tool(prompt, sql_output=sql_output)
                if plot_output.error:
                    st.info(f"Graphique non généré : {plot_output.error}")
            except Exception as e:
                logging.exception("Erreur pendant run_plot_tool")
                st.info(f"Une erreur est survenue lors de la génération du graphique : {e}")

        # === 4. Construction du prompt final et génération de la réponse ===
        final_prompt_for_llm = SYSTEM_PROMPT.format(
            text_context=text_context, sql_context=sql_context, question=prompt
        )
        messages_for_api = [{"role": "user", "content": final_prompt_for_llm}]

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.text("...")
            response_content = generer_reponse(messages_for_api)
            message_placeholder.write(response_content)

            # Affichage du graphique généré par le PlotTool, s'il y en a un
            if plot_output is not None and plot_output.chart_base64:
                import base64
                st.image(
                    base64.b64decode(plot_output.chart_base64),
                    caption=plot_output.title or "Graphique généré automatiquement",
                )

            # Traçabilité visible pour les coachs/analystes (transparence sur les sources)
            if sql_output is not None and not sql_output.error and sql_output.row_count > 0:
                with st.expander("🔎 Détail de la requête SQL utilisée"):
                    st.code(sql_output.generated_sql, language="sql")

        st.session_state.messages.append({"role": "assistant", "content": response_content})
        logfire.info(
            "question_answered",
            question=prompt,
            used_sql=route.needs_sql,
            used_text_context=route.needs_text_context,
            used_plot=route.needs_plot,
        )

st.markdown("---")
st.caption("Powered by Mistral AI, Faiss & SQL Tool | Data-driven NBA Insights")
