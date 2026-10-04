# Étape 3d – OCR classique vs VLM (mêmes pages)

Pages spécimen 01 (couverture), 03 (grossesse, tableau des visites), 04 (accouchement)
+ vraie photo 1-4 (sans vérité terrain remplie : qualitatif seulement). RTX 2050 4 Go, CPU pour l'OCR.

| Moteur | Exactitude | Couverture | Erreurs silencieuses | Cases P / R | Temps / page |
|---|---|---|---|---|---|
| VLM qwen2.5vl:3b (3b, après corrections) | 9,8 % | 15,0 % | 0 | 12,5 % / 12,5 % | ~352 s (333 / 663 / 60) |
| **EasyOCR** (CPU) + géométrie 3a | **88,0 %** | 97,7 % | 2 → 0* | 100 % / 75 %** | **37 s** |
| PaddleOCR 3.7 (CPU, .venv-ocr py3.13) | 87,2 % | 99,2 % | 2 | — / 0 %** | 107 s |

\* Les 2 erreurs silencieuses d'EasyOCR étaient des fautes de frappe (« Nbrmaux », « Ou; ») :
désormais corrigées vers le vocabulaire du carnet AVEC confiance plafonnée (A_REVISER).
\*\* Mesuré pendant le remplacement des cases ; le module définitif `ai/checkboxes.py`
(homographie sur les libellés + taux d'encre) donne **100 % / 100 %** sur les 8 pages de la
patiente 1 (`eval/reports/cases_avant_apres.md`, VLM avant : 27,4 % / 60,5 %).

Vraie photo 1-4 : EasyOCR ne reconnaît pas le type de page (écriture cursive, photo inclinée) ;
PaddleOCR le reconnaît mais ne rattache qu'un champ ; le VLM a planté (erreurs 500 d'Ollama à la
classification, désormais rattrapées). Les vraies photos restent le point faible : la saisie guidée
et la vérification sur WhatsApp prennent le relais.

**Gagnant : EasyOCR** (même exactitude que PaddleOCR, 3× plus rapide, installé dans le venv
principal). Mode par défaut : `AI_MODE=ocr`, `AI_OCR_ENGINE=easyocr` ; `--mode vlm` reste disponible.
