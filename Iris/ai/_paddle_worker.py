"""Exécuté par `.venv-ocr` (Python 3.13 + PaddleOCR) : image PNG sur stdin -> JSON sur stdout.

Une ligne JSON : [{"text", "box": [x0, y0, x1, y1], "conf"}]. Gère l'API v2 (`ocr.ocr()`)
et v3 (`predict()`). L'image ne touche jamais le disque.
"""
import io
import json
import sys

import numpy as np
from PIL import Image


def main() -> None:
    img = np.asarray(Image.open(io.BytesIO(sys.stdin.buffer.read())).convert("RGB"))
    import paddleocr
    from paddleocr import PaddleOCR
    major = int(str(getattr(paddleocr, "__version__", "2")).split(".")[0])
    out = []
    if major >= 3:
        ocr = PaddleOCR(lang="fr", use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False)
        for res in ocr.predict(img[:, :, ::-1]):           # BGR attendu
            r = res.json.get("res", res.json) if hasattr(res, "json") else res
            for text, score, box in zip(r["rec_texts"], r["rec_scores"], r["rec_boxes"]):
                x0, y0, x1, y1 = [float(v) for v in box]
                out.append({"text": text, "box": [x0, y0, x1, y1], "conf": float(score)})
    else:
        ocr = PaddleOCR(lang="fr", use_angle_cls=False, show_log=False)
        for line in (ocr.ocr(img[:, :, ::-1], cls=False) or [[]])[0] or []:
            pts, (text, score) = line
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            out.append({"text": text, "box": [min(xs), min(ys), max(xs), max(ys)], "conf": float(score)})
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
