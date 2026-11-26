"""WhatsApp da VolupIA (spec 59): um número da casa no gateway de canais; cada pessoa vincula o PRÓPRIO número mandando um
código do próprio aparelho (prova de posse sem SMS). A conversa pelo WhatsApp é a mesma conversa privada do app.

Gateway: contrato `chatwoot-rt/docs/canais/CONTRATO_GATEWAY.md` (mesmo cliente do Atende AI). Avisos ao casal nunca levam o
tema nem o desejo: só "tem novidade no Núcleo" (a tela do celular pode estar à vista de outra pessoa).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

import httpx

CONTA_CASA = 7100001          # conta fixa da VolupIA no gateway (Atende AI usa 7000000 + usuário)
CODIGO_VALE_S = 15 * 60
CODIGO_TENTATIVAS = 5
PADRAO_CODIGO = re.compile(r"AZUL[-\s]?(\d{6})", re.I)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS whats_casa (id INTEGER PRIMARY KEY, conexao TEXT NOT NULL, estado TEXT NOT NULL, numero TEXT NOT NULL DEFAULT '',
  segredo TEXT NOT NULL, atualizado REAL NOT NULL);
CREATE TABLE IF NOT EXISTS whats_vinculos (usuario INTEGER PRIMARY KEY, conversa TEXT UNIQUE, numero TEXT NOT NULL DEFAULT '',
  avisos INTEGER NOT NULL DEFAULT 1, vinculado REAL);
CREATE TABLE IF NOT EXISTS whats_codigos (usuario INTEGER PRIMARY KEY, hash TEXT NOT NULL, expira REAL NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS whats_eventos (id TEXT PRIMARY KEY, recebido REAL NOT NULL);
"""


class CanalErro(Exception):
    def __init__(self, status: int, codigo: str):
        super().__init__(f"{status} {codigo}")
        self.status, self.codigo = status, codigo


class Gateway:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/") + "/internal/channels"
        self.token, self.transport = token, transport

    def _r(self, metodo: str, caminho: str, **kw) -> dict:
        if not self.token:
            raise CanalErro(503, "gateway_sem_token")
        try:
            with httpx.Client(transport=self.transport, timeout=60) as h:
                r = h.request(metodo, self.url + caminho, headers={"Authorization": f"Bearer {self.token}"}, **kw)
        except httpx.HTTPError as e:
            raise CanalErro(503, "gateway_fora") from e
        if r.status_code >= 400:
            try:
                d = r.json().get("detail")
            except ValueError:
                d = None
            raise CanalErro(r.status_code, str(d or "erro"))
        return r.json() if r.content else {}

    def conectar(self) -> dict:
        return self._r("POST", "/connections", json={"account_id": CONTA_CASA, "provider": "whatsapp", "actor_id": "admin",
                                                     "consent": {"accepted": True, "version": "boateazul-2026-11"}, "login_flow": "qr"})

    def status(self, cid: str) -> dict:
        return self._r("GET", f"/connections/{cid}", params={"account_id": CONTA_CASA})

    def acao(self, cid: str, acao: str) -> dict:
        corpo = {"account_id": CONTA_CASA} if acao == "cancel" else {"account_id": CONTA_CASA, "actor_id": "admin"}
        return self._r("POST", f"/connections/{cid}/{acao}", json=corpo)

    def entrega(self, cid: str, url: str, segredo: str) -> dict:
        return self._r("PUT", f"/connections/{cid}/delivery", json={"account_id": CONTA_CASA, "webhook_url": url, "webhook_secret": segredo, "inbox_ref": "boateazul"})

    def enviar(self, cid: str, conversa: str, texto: str, chave: str) -> dict:
        return self._r("POST", f"/connections/{cid}/send", json={"account_id": CONTA_CASA, "idempotency_key": chave, "conversation_ref": conversa, "text": texto})


def assinatura_ok(segredo: str, ts: str, assinatura: str, corpo: bytes, tolerancia: int = 300) -> bool:
    """Mesma regra do gateway: HMAC_SHA256(segredo, "<ts>.<corpo>"), janela de 5 minutos."""
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - t) > tolerancia:
        return False
    esperado = "sha256=" + hmac.new(segredo.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura or "")


def _h(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()


def novo_codigo(db, uid: int, agora: float) -> str:
    cod = f"{secrets.randbelow(10**6):06d}"
    db.exec("INSERT INTO whats_codigos(usuario,hash,expira,tentativas) VALUES(?,?,?,0) ON CONFLICT(usuario) DO UPDATE SET hash=excluded.hash, expira=excluded.expira, tentativas=0",
            (uid, _h(cod), agora + CODIGO_VALE_S))
    return "AZUL-" + cod


def dono_do_codigo(db, texto: str, agora: float) -> int | None:
    """Quem gerou o código que veio na mensagem (válido e dentro do prazo)."""
    m = PADRAO_CODIGO.search(texto or "")
    if not m:
        return None
    r = db.um("SELECT usuario FROM whats_codigos WHERE hash=? AND expira>? AND tentativas<?", (_h(m.group(1)), agora, CODIGO_TENTATIVAS))
    return r["usuario"] if r else None


def numero_de(conversa: dict) -> str:
    """Dígitos do telefone a partir do contato do gateway (ponte do WhatsApp usa o número no id)."""
    c = conversa.get("contact") or {}
    for v in (c.get("external_id"), conversa.get("external_id"), c.get("username"), c.get("name")):
        d = re.sub(r"\D", "", str(v or ""))
        if 10 <= len(d) <= 15:
            return d
    return ""


def mascarar(numero: str) -> str:
    return ("+" + numero[:2] + " " + "•" * max(0, len(numero) - 6) + numero[-4:]) if numero else ""
