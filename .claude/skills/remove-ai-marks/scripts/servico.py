#!/usr/bin/env python3
"""Serviço HTTP local de limpeza de Unicode e pontuação estatística (só texto).

Expõe o contrato que a skill remove-ai-marks espera, restrito ao que os scripts
desta pasta fazem de verdade:

    GET  /health         {"ok": true, "version": ...}
    GET  /capabilities   o que este serviço tem e o que não tem
    POST /inspect        {"file": "<base64>", "name": "notas.md"}
    POST /clean          idem + "options": {nfkc, aggressive_homoglyphs, nbsp,
                                            detect_before, detect_after}
    POST /detect         pontuador estatístico (heurístico) sobre o texto

Não faz: reescrita estatística (Camada B), remoção de metadados/C2PA de imagens,
PDF ou DOCX, nem remoção de marca d'água em pixels, áudio ou vídeo.

Uso:  python3 servico.py [--host 127.0.0.1] [--port 8765]
Variáveis: WATERMARKS_SERVICE_PORT, WATERMARKS_SERVER_API_KEY (exige
"Authorization: Bearer <chave>" em todas as rotas quando definida).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpar_unicode  # noqa: E402
import pontuador_estatistico  # noqa: E402

VERSAO = "local-1.0"
MAX_CORPO = 20 * 1024 * 1024
OPCOES_TEXTO = {"nfkc", "aggressive_homoglyphs", "nbsp", "detect_before", "detect_after"}
EXT_BINARIAS = {
    ".png", ".jpg", ".jpeg", ".webp", ".avif", ".heic", ".bmp", ".gif", ".tiff", ".tif",
    ".pdf", ".docx", ".odt", ".epub", ".xlsx", ".pptx", ".mp4", ".mov", ".wav", ".mp3", ".flac",
}


class Erro(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status


def _texto_do_pedido(corpo: dict) -> tuple[str, str]:
    nome = str(corpo.get("name") or "texto.txt")
    arquivo = corpo.get("file")
    if not isinstance(arquivo, str):
        raise Erro(400, 'campo "file" (base64) é obrigatório')
    try:
        dados = base64.b64decode(arquivo, validate=True)
    except (binascii.Error, ValueError):
        raise Erro(400, 'campo "file" não é base64 válido') from None
    if Path(nome).suffix.lower() in EXT_BINARIAS or b"\x00" in dados[:8192]:
        return nome, ""
    try:
        return nome, dados.decode("utf-8")
    except UnicodeDecodeError:
        return nome, ""


def _deteccao(texto: str) -> dict:
    return {
        "detector": "stylometry",
        "tipo": "heuristica_nao_calibrada",
        "nota": "Não é detector de fornecedor nem de marca d'água; não prova autoria.",
        "resultado": pontuador_estatistico.pontuar(texto),
    }


def capacidades() -> dict:
    return {
        "ok": True,
        "version": VERSAO,
        "kinds": ["text"],
        "layer_a_unicode": True,
        "layer_b_rewrite": False,
        "scorers": {"stylometry": True, "synthid": False, "synthid_http": False},
        "text_detectors": {"markllm": False, "claude-text": False},
        "tools": {"c2patool": False, "exiftool": False, "qpdf": False, "ghostscript": False, "ffmpeg": False},
        "pixel_backends": {"ctrlregen": False, "diffusion": False},
        "harnesses": {"markllm": False},
        "clean_options": sorted(OPCOES_TEXTO),
    }


def inspecionar(corpo: dict) -> dict:
    _, texto = _texto_do_pedido(corpo)
    if not texto:
        return {"ok": True, "kind": "unknown", "suspicious": False,
                "report": {"nota": "Este serviço local só inspeciona texto UTF-8."}}
    rel = limpar_unicode.inspecionar(texto, nbsp=bool((corpo.get("options") or {}).get("nbsp")))
    return {"ok": True, "kind": "text", "suspicious": rel["suspeito"], "report": rel}


def limpar(corpo: dict) -> dict:
    nome, texto = _texto_do_pedido(corpo)
    if not texto:
        raise Erro(400, f"{nome}: formato não suportado. Este serviço local só limpa texto UTF-8 "
                        "(não trata metadados de imagem, PDF ou DOCX).")
    opcoes = corpo.get("options") or {}
    if not isinstance(opcoes, dict):
        raise Erro(400, '"options" deve ser um objeto')
    if opcoes.get("strategy"):
        raise Erro(400, 'opção "strategy" (reescrita da Camada B) não existe neste serviço local')
    limpo, camada_a = limpar_unicode.limpar(
        texto,
        nfkc=bool(opcoes.get("nfkc")),
        homoglifos=bool(opcoes.get("aggressive_homoglyphs")),
        nbsp=bool(opcoes.get("nbsp")),
    )
    relatorio = {
        "layer_a": camada_a,
        "layer_b": {"applied": False, "reason": "reescrita não disponível neste serviço local"},
    }
    ignoradas = sorted(set(opcoes) - OPCOES_TEXTO)
    if ignoradas:
        relatorio["ignored_options"] = ignoradas
    if opcoes.get("detect_before") or opcoes.get("detect_after"):
        relatorio["text_detectors"] = {}
        if opcoes.get("detect_before"):
            relatorio["text_detectors"]["before"] = [_deteccao(texto)]
        if opcoes.get("detect_after"):
            relatorio["text_detectors"]["after"] = [_deteccao(limpo)]
    return {"ok": True, "kind": "text",
            "cleaned": base64.b64encode(limpo.encode("utf-8")).decode("ascii"), "report": relatorio}


def detectar(corpo: dict) -> dict:
    nome, texto = _texto_do_pedido(corpo)
    if not texto:
        raise Erro(400, f"{nome}: o pontuador só aceita texto UTF-8")
    return {"ok": True, "kind": "text", "detections": [_deteccao(texto)]}


ROTAS_POST = {"/inspect": inspecionar, "/clean": limpar, "/detect": detectar}


class Manipulador(BaseHTTPRequestHandler):
    server_version = "remove-ai-marks-local/" + VERSAO

    def log_message(self, formato, *args):  # log curto, sem corpo dos pedidos
        sys.stderr.write("%s %s\n" % (self.address_string(), formato % args))

    def _responder(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _autorizado(self) -> bool:
        chave = os.environ.get("WATERMARKS_SERVER_API_KEY", "")
        if not chave:
            return True
        recebido = self.headers.get("Authorization", "")
        return hmac.compare_digest(recebido.encode(), f"Bearer {chave}".encode())

    def do_GET(self):
        if not self._autorizado():
            return self._responder(401, {"ok": False, "error": "não autorizado"})
        rota = self.path.split("?", 1)[0]
        if rota == "/health":
            return self._responder(200, {"ok": True, "version": VERSAO})
        if rota == "/capabilities":
            return self._responder(200, capacidades())
        self._responder(404, {"ok": False, "error": "rota inexistente"})

    def do_POST(self):
        if not self._autorizado():
            return self._responder(401, {"ok": False, "error": "não autorizado"})
        funcao = ROTAS_POST.get(self.path.split("?", 1)[0])
        if not funcao:
            return self._responder(404, {"ok": False, "error": "rota inexistente"})
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho <= 0 or tamanho > MAX_CORPO:
                raise Erro(413 if tamanho > MAX_CORPO else 400, "corpo ausente ou acima de 20 MB")
            try:
                corpo = json.loads(self.rfile.read(tamanho))
            except (ValueError, UnicodeDecodeError):
                raise Erro(400, "corpo não é JSON válido") from None
            if not isinstance(corpo, dict):
                raise Erro(400, "corpo deve ser um objeto JSON")
            self._responder(200, funcao(corpo))
        except Erro as erro:
            self._responder(erro.status, {"ok": False, "error": str(erro)})


def criar_servidor(host: str, porta: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, porta), Manipulador)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Serviço local de limpeza de Unicode e pontuação estatística.")
    p.add_argument("--host", default="127.0.0.1", help="padrão: só a própria máquina")
    p.add_argument("--port", type=int, default=int(os.environ.get("WATERMARKS_SERVICE_PORT", "8765")))
    args = p.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("WATERMARKS_SERVER_API_KEY"):
        print("erro: para expor fora da própria máquina, defina WATERMARKS_SERVER_API_KEY.", file=sys.stderr)
        return 2
    try:
        servidor = criar_servidor(args.host, args.port)
    except OSError as erro:
        print(f"erro: não foi possível abrir {args.host}:{args.port} ({erro})", file=sys.stderr)
        return 2
    print(f"remove-ai-marks local em http://{args.host}:{args.port}", file=sys.stderr, flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
