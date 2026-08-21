"""
evaluate_ocr.py — Évaluation avant/après du fallback OCR Nanonets.

Contexte (21/08/2026) : Sarah a demandé, dans le brief "aller plus loin", de
remplacer EasyOCR par Nanonets OCR dans le pipeline d'ingestion des rapports
en image, puis d'évaluer l'amélioration du taux de reconnaissance.

Aucun rapport scanné réel n'existe dans inputs/ (seulement des archives texte
Reddit) : ce script génère donc un document de test synthétique reproductible
— un texte de référence connu ("ground truth"), rendu comme une image puis
enregistré en PDF sans couche de texte (donc illisible par l'extraction PDF
standard, comme un vrai rapport scanné). Il compare ensuite :

  - AVANT  : extraction standard seule (PyPDF2), sans OCR
  - APRÈS  : extraction standard + fallback OCR Nanonets (utils/data_loader.py)

Score utilisé : similarité de séquence (difflib.SequenceMatcher.ratio()) entre
le texte extrait et le texte de référence — proxy simple du taux de
reconnaissance, 0.0 (rien de correct) à 1.0 (extraction parfaite).

Usage :
    python evaluate_ocr.py
Nécessite NANONETS_API_KEY dans .env pour la partie "après" (voir
.env.example). Sans clé, le script s'exécute quand même et rapporte le score
"après" comme égal au score "avant" (fallback non déclenché), ce qui est
documenté dans la sortie plutôt que de planter.
"""
from __future__ import annotations

import csv
import difflib
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("evaluate_ocr")

GROUND_TRUTH_TEXT = (
    "Rapport de performance - Saison reguliere 2025-2026\n"
    "Les Boston Celtics dominent la conference Est avec un bilan de 58 victoires "
    "pour 24 defaites. Jayson Tatum termine meilleur marqueur de l'equipe avec "
    "27.3 points de moyenne par match, devant Jaylen Brown a 23.1 points.\n"
    "Cote Ouest, le Thunder d'Oklahoma City conserve la meilleure defense de la "
    "ligue avec seulement 106.4 points encaisses par match en moyenne."
)

FIXTURES_DIR = Path("data") / "ocr_test"
SCANNED_PDF_PATH = FIXTURES_DIR / "rapport_scanne_test.pdf"
OUTPUT_CSV = Path("reports") / "ocr_before_after.csv"


def _generate_synthetic_scanned_pdf(path: Path) -> None:
    """Rend GROUND_TRUTH_TEXT dans une image puis l'enregistre en PDF sans
    couche de texte — simule un rapport scanné (image pure), reproductible
    sans dépendre d'un vrai fichier scanné indisponible dans ce projet."""
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 1240, 900  # ~A4 à 150 DPI
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    font = None
    for font_path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if Path(font_path).exists():
            font = ImageFont.truetype(font_path, 28)
            break
    if font is None:
        font = ImageFont.load_default()

    margin = 60
    y = margin
    for line in GROUND_TRUTH_TEXT.split("\n"):
        # retour à la ligne manuel simple (largeur fixe ~90 caractères)
        while len(line) > 90:
            cut = line.rfind(" ", 0, 90)
            cut = cut if cut > 0 else 90
            draw.text((margin, y), line[:cut], fill="black", font=font)
            line = line[cut:].strip()
            y += 40
        draw.text((margin, y), line, fill="black", font=font)
        y += 40

    img.save(path, "PDF")
    logger.info(f"Document scanné synthétique généré : {path}")


def _similarity(reference: str, candidate: str) -> float:
    if not candidate:
        return 0.0
    return difflib.SequenceMatcher(None, reference.strip(), candidate.strip()).ratio()


def run_evaluation() -> None:
    from PyPDF2 import PdfReader
    from utils.data_loader import extract_text_from_pdf
    from utils.config import NANONETS_API_KEY

    if not SCANNED_PDF_PATH.exists():
        _generate_synthetic_scanned_pdf(SCANNED_PDF_PATH)
    else:
        logger.info(f"Document de test déjà présent : {SCANNED_PDF_PATH}")

    # --- AVANT : extraction standard seule (sans passer par le fallback) ---
    reader = PdfReader(str(SCANNED_PDF_PATH))
    before_text = "".join(page.extract_text() or "" for page in reader.pages)
    before_score = _similarity(GROUND_TRUTH_TEXT, before_text)

    # --- APRÈS : extraction standard + fallback OCR Nanonets ---
    if not NANONETS_API_KEY:
        logger.warning(
            "NANONETS_API_KEY absente : la partie 'après' ne peut pas être "
            "mesurée réellement. Ajoutez la clé dans .env (voir "
            ".env.example) puis relancez ce script pour un vrai résultat."
        )
        after_text = before_text
        after_score = before_score
        note = "NANONETS_API_KEY absente — fallback OCR non déclenché, score identique à 'avant'"
    else:
        after_text = extract_text_from_pdf(str(SCANNED_PDF_PATH)) or ""
        after_score = _similarity(GROUND_TRUTH_TEXT, after_text)
        note = "OCR Nanonets exécuté avec succès" if after_score > before_score else "OCR exécuté mais sans amélioration mesurée"

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "chars_extracted", "similarity_score", "note"])
        writer.writerow(["before_no_ocr", len(before_text.strip()), round(before_score, 4), "Extraction PyPDF2 standard uniquement"])
        writer.writerow(["after_with_ocr", len(after_text.strip()), round(after_score, 4), note])

    logger.info("--- Résultats OCR avant / après ---")
    logger.info(f"AVANT (PyPDF2 seul)      : {len(before_text.strip())} caractères, similarité = {before_score:.4f}")
    logger.info(f"APRÈS (+ OCR Nanonets)    : {len(after_text.strip())} caractères, similarité = {after_score:.4f}")
    logger.info(f"Amélioration             : {after_score - before_score:+.4f}")
    logger.info(f"Résultats écrits dans {OUTPUT_CSV}")


if __name__ == "__main__":
    run_evaluation()
