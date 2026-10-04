"""Client Ollama minimal (POST /api/generate), 100 % local.

- `format` = schéma JSON (structured outputs), température 0, num_ctx 8192 ;
- 2 tentatives ; si la réponse est vide ou n'est pas du JSON valide, nouvel
  essai SANS `format` puis extraction du premier objet JSON du texte ;
- cache disque optionnel (clé = sha256(images) + modèle + prompt + schéma) pour
  itérer sur la normalisation sans relancer le modèle. Réservé au CLI et à
  l'évaluation : le worker backend ne l'active jamais (rien d'une vraie photo
  ne doit atterrir sur disque en clair).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("iris.ai")


class OllamaUnavailable(Exception):
    """Le serveur Ollama ne répond pas (arrêté, mauvais port...)."""


class OllamaError(Exception):
    """Réponse inexploitable après toutes les tentatives."""


@dataclass
class GenResult:
    data: dict
    model: str
    duration_s: float
    done_reason: str | None = None
    eval_count: int | None = None
    cached: bool = False
    retried_without_format: bool = False


def first_json_object(text: str) -> dict | None:
    """Premier objet JSON équilibré trouvé dans un texte (réponses bavardes, ```json ...```)."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def repair_truncated_json(text: str) -> dict | None:
    """Réponse coupée par num_predict (le modèle bouclait) : on recule jusqu'à la dernière virgule
    qui laisse un JSON valide une fois les accolades refermées -> on garde les paires complètes."""
    start = text.find("{")
    if start == -1:
        return None
    body = text[start:]
    cuts = [i for i, c in enumerate(body) if c == ","][::-1][:400]
    for cut in cuts:
        head = body[:cut]
        stack, in_str, esc = [], False, False
        for c in head:
            if in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in "{[":
                stack.append("}" if c == "{" else "]")
            elif c in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            obj = json.loads(head + "".join(reversed(stack)))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


class OllamaClient:
    def __init__(self, url: str = "http://localhost:11434", timeout: float = 600, attempts: int = 2,
                 num_ctx: int = 8192, num_predict: int = 2048, cache_dir: Path | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self.attempts = attempts
        self.num_ctx = num_ctx
        self.num_predict = num_predict      # plafond de sortie : un modèle qui boucle ne bloque pas 15 min
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._http = httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0), transport=transport)

    # ------------------------------------------------------------ utilitaires
    def ping(self) -> list[str]:
        """Liste des modèles installés ; lève OllamaUnavailable si le serveur ne répond pas."""
        try:
            r = self._http.get(f"{self.url}/api/tags", timeout=3)
            r.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
            raise OllamaUnavailable(f"Ollama injoignable sur {self.url} : {e}") from e
        return [m["name"] for m in r.json().get("models", [])]

    def _cache_path(self, model: str, prompt: str, images: list[bytes], schema: dict | None) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha256()
        for img in images:
            h.update(hashlib.sha256(img).digest())
        h.update(model.encode())
        h.update(prompt.encode())
        h.update(json.dumps(schema, sort_keys=True).encode())
        return self.cache_dir / f"{h.hexdigest()}.json"

    def _post(self, payload: dict) -> dict:
        try:
            r = self._http.post(f"{self.url}/api/generate", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise OllamaUnavailable(f"Ollama injoignable sur {self.url} : {e}") from e
        if r.status_code == 404:
            raise OllamaError(f"modèle absent : {payload['model']} (ollama pull {payload['model']})")
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------ génération
    def generate(self, model: str, prompt: str, images: list[bytes] | None = None,
                 schema: dict | None = None, use_cache: bool = True, num_predict: int | None = None) -> GenResult:
        images = images or []
        cpath = self._cache_path(model, prompt, images, schema) if use_cache else None
        if cpath and cpath.exists():
            return GenResult(json.loads(cpath.read_text(encoding="utf-8")), model, 0.0, cached=True)

        base = {"model": model, "prompt": prompt, "stream": False, "keep_alive": "15m",
                "images": [base64.b64encode(i).decode() for i in images],
                "options": {"temperature": 0, "num_ctx": self.num_ctx,
                            "num_predict": min(num_predict or self.num_predict, self.num_predict)}}
        plans = [True] * self.attempts + [False]        # avec schéma, puis sans
        last_err = "réponse vide"
        t0 = time.monotonic()
        grammar_crash = False
        for i, with_format in enumerate(plans):
            if grammar_crash and with_format:
                continue                                 # même schéma = même plantage : on passe au sans-format
            payload = dict(base, format=schema) if (with_format and schema) else dict(base)
            try:
                resp = self._post(payload)
            except httpx.ReadTimeout:
                last_err = "délai dépassé"
                log.warning("Ollama %s : délai dépassé (tentative %d)", model, i + 1)
                continue
            except httpx.HTTPStatusError as e:
                # 500 sur requête avec schéma : llama.cpp plante sur la grammaire
                # (« Unexpected empty grammar stack ») -> inutile de réessayer le même schéma
                last_err = str(e)
                grammar_crash = grammar_crash or (with_format and e.response.status_code >= 500)
                log.warning("Ollama %s : %s (tentative %d)", model, last_err[:120], i + 1)
                continue
            text = (resp.get("response") or "").strip()
            log.info("Ollama %s : done_reason=%s eval_count=%s durée=%.1fs%s", model, resp.get("done_reason"),
                     resp.get("eval_count"), (resp.get("total_duration") or 0) / 1e9,
                     "" if with_format else " (sans format)")
            data = None
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = first_json_object(text)
                    if data is None and resp.get("done_reason") == "length":
                        data = repair_truncated_json(text)      # sortie coupée : on garde le début
                        if data is not None:
                            log.warning("Ollama %s : réponse tronquée (num_predict=%d), paires complètes gardées",
                                        model, self.num_predict)
            if isinstance(data, dict):
                res = GenResult(data, model, time.monotonic() - t0, resp.get("done_reason"),
                                resp.get("eval_count"), retried_without_format=not with_format)
                if cpath:
                    cpath.parent.mkdir(parents=True, exist_ok=True)
                    cpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return res
            last_err = "réponse vide" if not text else "JSON invalide"
            log.warning("Ollama %s : %s (tentative %d/%d)", model, last_err, i + 1, len(plans))
        raise OllamaError(f"{model} : {last_err} après {len(plans)} tentatives")
