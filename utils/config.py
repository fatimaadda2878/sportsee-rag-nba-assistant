# utils/config.py
import os
from dotenv import load_dotenv

# Charger les variables d'environnement du fichier .env
load_dotenv()

# --- Clé API ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    print("⚠️ Attention: La clé API Mistral (MISTRAL_API_KEY) n'est pas définie dans le fichier .env")
    # raise ValueError("Clé API Mistral manquante. Veuillez la définir dans le fichier .env")

# --- Modèles Mistral ---
EMBEDDING_MODEL = "mistral-embed"
MODEL_NAME = "mistral-small-latest"  # Ou un autre modèle comme mistral-large-latest

# --- Configuration de l'Indexation ---
INPUT_DIR = "inputs"                # Dossier pour les données sources après extraction
VECTOR_DB_DIR = "vector_db"         # Dossier pour stocker l'index Faiss et les chunks
FAISS_INDEX_FILE = os.path.join(VECTOR_DB_DIR, "faiss_index.idx")
DOCUMENT_CHUNKS_FILE = os.path.join(VECTOR_DB_DIR, "document_chunks.pkl")

CHUNK_SIZE = 1500                   # Taille des chunks en *caractères* (vise ~512 tokens)
CHUNK_OVERLAP = 150                 # Chevauchement en *caractères*
EMBEDDING_BATCH_SIZE = 32           # Taille des lots pour l'API d'embedding

# --- Configuration de la Recherche ---
SEARCH_K = 5                        # Nombre de documents à récupérer par défaut

# --- Configuration de la Base de Données applicative (historique, cache) ---
DATABASE_DIR = "database"
DATABASE_FILE = os.path.join(DATABASE_DIR, "interactions.db")

# --- Configuration de l'Application ---
APP_TITLE = "NBA Analyst AI"
NAME = "NBA"  # Nom à personnaliser dans l'interface

# ============================================================
# --- Étape 2 : Base de données métier (players/matches/stats/reports) ---
# ============================================================
# PostgreSQL est la base de données cible du projet (cf. consignes) : c'est la
# valeur par défaut ci-dessous si DATABASE_URL n'est pas définie dans le .env.
# SQLite reste disponible en dépannage (démo hors-ligne sans serveur) en
# définissant DATABASE_URL="sqlite:///database/sportsee.db" dans le .env — le
# code (SQLAlchemy) ne change pas, seul le dialecte de l'URL change.
SQL_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/sportsee"
)

# Chemin du fichier Excel source pour l'ingestion (Étape 2)
EXCEL_SOURCE_FILE = os.getenv("EXCEL_SOURCE_FILE", "data/regular_NBA.xlsx")

# Nombre max de lignes de résultat retournées par le SQL Tool (garde-fou)
SQL_TOOL_MAX_ROWS = 200

# ============================================================
# --- Observabilité : Pydantic Logfire ---
# ============================================================
LOGFIRE_TOKEN = os.getenv("LOGFIRE_TOKEN")
LOGFIRE_DISABLE = os.getenv("LOGFIRE_DISABLE", "false").lower() == "true"
LOGFIRE_SERVICE_NAME = "sportsee-rag"

# ============================================================
# --- OCR (Nanonets/Docstrange) : fallback pour les PDF scannés (rapports en image) ---
# ============================================================
# Compte gratuit : https://docstrange.nanonets.com (clé dans le menu en haut
# à droite une fois connecté — PAS la clé de l'ancienne page
# app.nanonets.com/#/keys, incompatible avec l'API actuelle).
# Si absente, l'OCR est simplement désactivé (pas de crash, extraction PDF
# standard uniquement) — voir utils/data_loader.py.
NANONETS_API_KEY = os.getenv("NANONETS_API_KEY")

# Seuil (en caractères) en dessous duquel l'extraction PDF standard est
# considérée comme un échec probable (PDF scanné/image) déclenchant le
# fallback OCR.
OCR_FALLBACK_MIN_CHARS = 100
