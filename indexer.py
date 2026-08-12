# indexer.py
import argparse
import logging
from typing import Optional

from utils.config import INPUT_DIR
from utils.data_loader import download_and_extract_zip, load_and_parse_files
from utils.vector_store import VectorStoreManager
from utils.observability import logfire

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def run_indexing(input_directory: str, data_url: Optional[str] = None):
    """Exécute le processus complet d'indexation."""
    with logfire.span("run_indexing", input_directory=input_directory):
        logging.info("--- Démarrage du processus d'indexation ---")

        if data_url:
            logging.info(f"Tentative de téléchargement depuis l'URL: {data_url}")
            success = download_and_extract_zip(data_url, input_directory)
            if not success:
                logging.error("Échec du téléchargement ou de l'extraction. Arrêt.")
                logfire.error("indexing_download_failed", url=data_url)
                return
        else:
            logging.info(f"Aucune URL fournie. Utilisation des fichiers locaux dans: {input_directory}")

        logging.info(f"Chargement et parsing des fichiers depuis: {input_directory}")
        documents = load_and_parse_files(input_directory)

        if not documents:
            logging.warning("Aucun document n'a été chargé ou parsé. Vérifiez le contenu du dossier d'entrée.")
            logging.info("--- Processus d'indexation terminé (aucun document traité) ---")
            logfire.info("indexing_no_documents", input_directory=input_directory)
            return

        logging.info("Initialisation du gestionnaire de Vector Store...")
        vector_store = VectorStoreManager()

        logging.info("Construction de l'index Faiss (cela peut prendre du temps)...")
        vector_store.build_index(documents)

        logging.info("--- Processus d'indexation terminé avec succès ---")
        logging.info(f"Nombre de documents traités: {len(documents)}")
        if vector_store.index:
            logging.info(f"Nombre de chunks indexés: {vector_store.index.ntotal}")
            logfire.info(
                "indexing_completed",
                nb_documents=len(documents),
                nb_chunks_indexed=vector_store.index.ntotal,
            )
        else:
            logging.warning("L'index final n'a pas pu être créé ou est vide.")
            logfire.info("indexing_empty_result")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Script d'indexation pour l'application RAG")
    parser.add_argument(
        "--input-dir",
        type=str,
        default=INPUT_DIR,
        help=f"Répertoire contenant les fichiers sources (par défaut: {INPUT_DIR})"
    )
    parser.add_argument(
        "--data-url",
        type=str,
        default=None,
        help="URL optionnelle pour télécharger et extraire un fichier inputs.zip"
    )
    args = parser.parse_args()

    run_indexing(input_directory=args.input_dir, data_url=args.data_url)
