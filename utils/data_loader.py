# utils/data_loader.py
import os
import requests
import zipfile
import io
from pathlib import Path
from typing import List, Dict, Optional, Union
import logging

from .config import NANONETS_API_KEY, OCR_FALLBACK_MIN_CHARS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Fonctions d'extraction de texte ---

NANONETS_EXTRACTION_ENDPOINT = "https://extraction-api.nanonets.com/api/v1/extract/sync"


def extract_text_with_ocr_nanonets(file_path: str) -> Optional[str]:
    """
    OCR de secours via l'API Nanonets/Docstrange (ajouté le 21/08/2026, à la
    demande de Sarah : "remplace EasyOCR par Nanonets OCR").

    N'est appelé QUE si l'extraction standard (PyPDF2) échoue, c'est-à-dire
    pour des PDF scannés/rapports en image sans couche de texte. Nécessite
    NANONETS_API_KEY (compte gratuit : https://docstrange.nanonets.com,
    récupérer la clé dans le menu en haut à droite une fois connecté). Sans
    clé configurée, retourne None silencieusement (pas de crash de
    l'ingestion) : voir extract_text_from_pdf.

    NB (21/08/2026) : implémenté en appel HTTP direct (requests + Bearer
    token) plutôt qu'avec le package `ocr-nanonets-wrapper`. Ce package
    cible l'ancienne API "app.nanonets.com/api/v2/OCR/FullText" (clé
    obtenue sur app.nanonets.com/#/keys) et, surtout, appelle `sys.exit()`
    en cas de clé invalide — inacceptable dans un pipeline qui doit
    dégrader gracieusement. L'API actuelle (docstrange.nanonets.com) est un
    produit distinct, avec ses propres clés : une clé de l'ancienne API ne
    fonctionne pas ici, et inversement.
    """
    if not NANONETS_API_KEY:
        logging.warning(
            f"OCR Nanonets non tenté pour {file_path} : NANONETS_API_KEY absente "
            f"du .env (voir .env.example)."
        )
        return None
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                NANONETS_EXTRACTION_ENDPOINT,
                headers={"Authorization": f"Bearer {NANONETS_API_KEY}"},
                files={"file": f},
                data={"output_format": "markdown"},
                timeout=60,
            )
        if response.status_code in (401, 403):
            logging.error(
                f"OCR Nanonets : authentification refusée ({response.status_code}) pour "
                f"{file_path}. Vérifiez que NANONETS_API_KEY provient bien de "
                f"https://docstrange.nanonets.com (et non de l'ancienne page "
                f"app.nanonets.com/#/keys, incompatible). Détail : {response.text[:200]}"
            )
            return None
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            logging.warning(f"OCR Nanonets : extraction non réussie pour {file_path} : {payload}")
            return None
        text = (payload.get("result") or {}).get("markdown", {}).get("content")
        if text and text.strip():
            logging.info(f"OCR Nanonets réussi pour {file_path} ({len(text)} caractères).")
            return text
        logging.warning(f"OCR Nanonets n'a extrait aucun texte pour {file_path}.")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur réseau OCR Nanonets pour {file_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur OCR Nanonets pour {file_path}: {e}")
        return None


def extract_text_from_pdf(file_path: str) -> Optional[str]:
    """
    Extrait le texte d'un fichier PDF : extraction standard (PyPDF2) d'abord,
    puis OCR Nanonets en repli si le résultat est trop pauvre (PDF scanné/
    rapport en image, sans couche de texte exploitable par PyPDF2).
    """
    try:
        from PyPDF2 import PdfReader
        reader_pdf = PdfReader(file_path)
        text = "".join(page.extract_text() + "\n" for page in reader_pdf.pages if page.extract_text())

        if len(text.strip()) < OCR_FALLBACK_MIN_CHARS:
            logging.warning(
                f"Peu de texte trouvé dans {file_path} via extraction standard "
                f"({len(text.strip())} caractères). Le fichier est peut-être un PDF "
                f"scanné (image) : tentative de fallback OCR (Nanonets)."
            )
            ocr_text = extract_text_with_ocr_nanonets(file_path)
            if ocr_text and len(ocr_text.strip()) > len(text.strip()):
                return ocr_text
            return text
        else:
            logging.info(f"Texte extrait de PDF: {file_path} ({len(text)} caractères)")
        return text
    except Exception as e:
        logging.error(f"Erreur extraction PDF {file_path}: {e}")
        return None


def extract_text_from_docx(file_path: str) -> Optional[str]:
    """Extrait le texte d'un fichier Word DOCX."""
    try:
        import docx
        doc = docx.Document(file_path)
        text = "\n".join(para.text for para in doc.paragraphs if para.text)
        logging.info(f"Texte extrait de DOCX: {file_path} ({len(text)} caractères)")
        return text
    except Exception as e:
        logging.error(f"Erreur extraction DOCX {file_path}: {e}")
        return None

def extract_text_from_txt(file_path: str) -> Optional[str]:
    """Extrait le texte d'un fichier texte brut."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        logging.info(f"Texte extrait de TXT: {file_path} ({len(text)} caractères)")
        return text
    except Exception as e:
        logging.error(f"Erreur extraction TXT {file_path}: {e}")
        return None

def extract_text_from_csv(file_path: str) -> Optional[str]:
    """Extrait le texte d'un fichier CSV (convertit en string)."""
    try:
        import pandas as pd
        try:
            df = pd.read_csv(file_path)
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='latin1')
        except Exception as read_e:
            logging.warning(f"Erreur lecture CSV {file_path}: {read_e}. Tentative avec séparateur ';'")
            try:
                df = pd.read_csv(file_path, sep=';')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, sep=';', encoding='latin1')
            except Exception as read_e2:
                logging.error(f"Impossible de lire le CSV {file_path}: {read_e2}")
                return None

        text = df.to_string()
        logging.info(f"Texte extrait de CSV: {file_path} ({len(text)} caractères)")
        return text
    except ImportError:
        logging.warning("Pandas non installé. Impossible de lire les fichiers CSV.")
        return None
    except Exception as e:
        logging.error(f"Erreur extraction CSV {file_path}: {e}")
        return None

def extract_text_from_excel(file_path: str) -> Optional[Union[str, Dict[str, str]]]:
    """Extrait le texte de chaque feuille d'un fichier Excel."""
    try:
        import pandas as pd
        excel_file = pd.ExcelFile(file_path)
        sheets_data = {}
        for sheet_name in excel_file.sheet_names:
            df = excel_file.parse(sheet_name)
            sheets_data[sheet_name] = df.to_string()

        logging.info(f"Texte extrait de {len(sheets_data)} feuille(s) dans Excel: {file_path}")
        if len(sheets_data) == 1:
            return list(sheets_data.values())[0]
        return sheets_data
    except ImportError:
        logging.warning("Pandas ou openpyxl non installé. Impossible de lire les fichiers Excel.")
        return None
    except Exception as e:
        logging.error(f"Erreur extraction Excel {file_path}: {e}")
        return None

# --- Fonctions de chargement ---

def download_and_extract_zip(url: str, output_dir: str) -> bool:
    """Télécharge un fichier ZIP depuis une URL et l'extrait."""
    if not url:
        logging.warning("Aucune URL fournie pour le téléchargement.")
        return False
    try:
        logging.info(f"Téléchargement des données depuis {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            logging.info(f"Extraction du contenu dans {output_dir}...")
            z.extractall(output_dir)
        logging.info("Téléchargement et extraction terminés.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de téléchargement: {e}")
        return False
    except zipfile.BadZipFile:
        logging.error("Le fichier téléchargé n'est pas un ZIP valide.")
        return False
    except Exception as e:
        logging.error(f"Erreur inattendue lors du téléchargement/extraction: {e}")
        return False

def load_and_parse_files(input_dir: str) -> List[Dict[str, any]]:
    """
    Charge et parse récursivement les fichiers d'un répertoire.
    Retourne une liste de dictionnaires, chacun représentant un document.
    """
    documents = []
    input_path = Path(input_dir)
    if not input_path.is_dir():
        logging.error(f"Le répertoire d'entrée '{input_dir}' n'existe pas.")
        return []

    logging.info(f"Parcours du répertoire source: {input_dir}")
    for file_path in input_path.rglob("*.*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(input_path)
            source_folder = relative_path.parts[0] if len(relative_path.parts) > 1 else "root"
            ext = file_path.suffix.lower()

            logging.debug(f"Traitement du fichier: {relative_path} (Dossier source: {source_folder})")

            extracted_content = None
            if ext == ".pdf":
                extracted_content = extract_text_from_pdf(str(file_path))
            elif ext == ".docx":
                extracted_content = extract_text_from_docx(str(file_path))
            elif ext == ".txt":
                extracted_content = extract_text_from_txt(str(file_path))
            elif ext == ".csv":
                extracted_content = extract_text_from_csv(str(file_path))
            elif ext in [".xlsx", ".xls"]:
                extracted_content = extract_text_from_excel(str(file_path))
            else:
                logging.warning(f"Type de fichier non supporté ignoré: {relative_path}")
                continue

            if not extracted_content:
                logging.warning(f"Aucun contenu n'a pu être extrait de {relative_path}")
                continue

            if isinstance(extracted_content, dict):
                for sheet_name, text in extracted_content.items():
                    documents.append({
                        "page_content": text,
                        "metadata": {
                            "source": f"{str(relative_path)} (Feuille: {sheet_name})",
                            "filename": file_path.name,
                            "sheet": sheet_name,
                            "category": source_folder,
                            "full_path": str(file_path.resolve())
                        }
                    })
            else:
                documents.append({
                    "page_content": extracted_content,
                    "metadata": {
                        "source": str(relative_path),
                        "filename": file_path.name,
                        "category": source_folder,
                        "full_path": str(file_path.resolve())
                    }
                })

    logging.info(f"{len(documents)} documents chargés et parsés.")
    return documents
