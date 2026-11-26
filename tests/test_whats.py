"""Spec 59: WhatsApp da Boate Azul com o gateway de canais simulado (transporte httpx falso)."""
from produtos_core.teste import entrar
import hashlib
import hmac
import json
import os
import time

os.environ["BOATE_SEM_APP"] = "1"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import whats  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import criar_app  # noqa: E402

ENVIADAS: list[dict] = []
SINAIS = {"sinais": []}


def llm_falso(msgs):
    if "Responda SÓ um JSON" in msgs[-1]["content"]:
        return json.dumps(SINAIS)
    return "Resposta privada da IA."


def gateway_falso(req: httpx.Request) -> httpx.Response:
    p = req.url.path
    if req.method == "POST" and p.endswith("/connections"):
        return httpx.Response(200, json={"connection": {"id": "con-1", "state": "pending_auth"}, "step": {"step_id": "s1", "kind": "qr", "qr": {"data": "2@QRFALSO"}}})
    if req.method == "PUT" and p.endswith("/delivery"):
        return httpx.Response(200, json={"ok": True})
    if req.method == "GET" and "/connections/con-1" in p:
        return httpx.Response(200, json={"connection": {"id": "con-1", "state": "connected", "external_label": "+55 62 99999-0000"}})
    if req.method == "POST" and p.endswith("/send"):
        ENVIADAS.append(json.loads(req.content))
        return httpx.Response(200, json={"outbox_id": "o1", "status": "queued"})
    if req.method == "POST" and p.endswith("/disconnect"):
        return httpx.Response(200, json={"connection": {"id": "con-1", "state": "disconnected"}})
    return httpx.Response(404, json={"detail": "nao_achei"})


@pytest.fixture
def amb(tmp_path, monkeypatch):
    ENVIADAS.clear()
    SINAIS["sinais"] = []
    monkeypatch.setenv("RT_ADMIN_USUARIO", "lucas")
    monkeypatch.setenv("RT_ADMIN_SENHA", "segredo")
    cfg = Config(dados=str(tmp_path), segredo_sessao="s", dev=True, canais_token="t")
    gw = whats.Gateway("http://gw", "t", transport=httpx.MockTransport(gateway_falso))
    app = criar_app(cfg, llm=llm_falso, gateway=gw)

    def pessoa(email, nome, nasc="1990-05-10"):
        c = TestClient(app)
        entrar(c, email)
        assert c.post("/api/perfil", json={"nome": nome, "nascimento": nasc}).status_code == 200
        return c
    adm = TestClient(app)
    assert adm.post("/api/painel/entrar", json={"usuario": "lucas", "senha": "segredo"}).status_code == 200
    return app, pessoa, adm


def ligar_casa(adm):
    r = adm.post("/api/painel/whats/conectar").json()
    assert r["qr"] == "2@QRFALSO" and r["estado"] == "pending_auth"
    r = adm.get("/api/painel/whats").json()  # o QR foi lido: o gateway diz conectado e informa o número
    assert r["estado"] == "connected" and r["numero"].endswith("0000")
    return r


def evento(app, corpo: dict, segredo: str | None = None):
    k = app.state.db.um("SELECT segredo FROM whats_casa WHERE id=1")
    cru = json.dumps(corpo).encode()
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new((segredo or k["segredo"]).encode(), f"{ts}.".encode() + cru, hashlib.sha256).hexdigest()
    return TestClient(app).post("/hooks/whats", content=cru, headers={"x-luar-timestamp": ts, "x-luar-signature": sig, "content-type": "application/json"})


def msg(app, numero: str, texto: str, eid: str):
    return evento(app, {"event_id": eid, "type": "message.created",
                        "conversation": {"external_id": f"room-{numero}", "contact": {"external_id": f"@whatsapp_{numero}:canais", "name": "X"}},
                        "message": {"external_id": "m-" + eid, "direction": "incoming", "text": texto}})


def para(numero):
    return [e["text"] for e in ENVIADAS if e["conversation_ref"] == f"room-{numero}"]


def test_admin_conecta_a_casa_e_so_admin(amb):
    app, pessoa, adm = amb
    assert TestClient(app).post("/api/painel/whats/conectar").status_code == 401
    ligar_casa(adm)


def test_vinculo_por_codigo_e_conversa_privada(amb):
    app, pessoa, adm = amb
    a = pessoa("ana@x.com", "Ana")
    assert a.get("/api/whats").json()["disponivel"] is False
    assert a.post("/api/whats/codigo").status_code == 503  # casa desligada: não promete o que não existe
    ligar_casa(adm)
    j = a.post("/api/whats/codigo").json()
    assert j["codigo"].startswith("AZUL-") and j["link"] == f"https://wa.me/5562999990000?text={j['codigo']}"
    assert msg(app, "5562911112222", f"oi {j['codigo']}", "e1").status_code == 200
    assert "vinculado" in para("5562911112222")[-1]
    w = a.get("/api/whats").json()
    assert w["vinculado"] and w["numero"].endswith("2222")
    # agora a conversa pelo Whats é a mesma do app
    msg(app, "5562911112222", "quero sair da rotina com ele", "e2")
    assert para("5562911112222")[-1] == "Resposta privada da IA."
    hist = [m["texto"] for m in a.get("/api/conversa").json()["mensagens"]]
    assert hist[-2:] == ["quero sair da rotina com ele", "Resposta privada da IA."]
    # evento repetido não responde de novo
    n = len(ENVIADAS)
    assert msg(app, "5562911112222", "quero sair da rotina com ele", "e2").json().get("repetido")
    assert len(ENVIADAS) == n


def test_codigo_invalido_e_numero_desconhecido(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    a = pessoa("ana@x.com", "Ana")
    a.post("/api/whats/codigo")
    msg(app, "5511900000001", "AZUL-000000", "e1")  # código que não existe
    assert "crie sua conta" in para("5511900000001")[-1]
    assert a.get("/api/whats").json()["vinculado"] is False
    # código vencido
    j = a.post("/api/whats/codigo").json()
    app.state.db.exec("UPDATE whats_codigos SET expira=0")
    msg(app, "5511900000001", j["codigo"], "e2")
    assert a.get("/api/whats").json()["vinculado"] is False


def test_numero_ja_usado_por_outra_conta(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    msg(app, "5562911112222", a.post("/api/whats/codigo").json()["codigo"], "e1")
    # outra conversa (outro aparelho) com o MESMO número tenta vincular a conta do Beto
    evento(app, {"event_id": "e2", "type": "message.created",
                 "conversation": {"external_id": "room-outra", "contact": {"external_id": "@whatsapp_5562911112222:canais"}},
                 "message": {"external_id": "m2", "direction": "incoming", "text": b.post("/api/whats/codigo").json()["codigo"]}})
    assert "outra conta" in [e["text"] for e in ENVIADAS if e["conversation_ref"] == "room-outra"][-1]
    assert b.get("/api/whats").json()["vinculado"] is False


def test_assinatura_errada_recusada(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    r = evento(app, {"event_id": "x", "type": "message.created"}, segredo="errado")
    assert r.status_code == 401


def test_limite_do_plano_gratis_vale_no_whats(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    a = pessoa("ana@x.com", "Ana")
    msg(app, "5562911112222", a.post("/api/whats/codigo").json()["codigo"], "v")
    for i in range(15):
        a.post("/api/conversa", json={"texto": f"msg {i}"})
    msg(app, "5562911112222", "mais uma", "e16")
    assert "15 mensagens por dia" in para("5562911112222")[-1]


def test_aviso_de_novidade_vai_para_os_dois_sem_o_tema(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    cod = a.post("/api/casal/criar").json()["codigo"]
    b.post("/api/casal/entrar", json={"codigo": cod})
    msg(app, "5562911112222", a.post("/api/whats/codigo").json()["codigo"], "va")
    msg(app, "5562933334444", b.post("/api/whats/codigo").json()["codigo"], "vb")
    b.post("/api/whats/avisos", json={"ligado": True})
    a.post("/api/sinal", json={"tema": "massagem", "estado": "vontade"})
    assert b.post("/api/sinal", json={"tema": "massagem", "estado": "curiosidade"}).json()["revelados"] == 1
    for n in ("5562911112222", "5562933334444"):
        aviso = para(n)[-1]
        assert "novidade no Núcleo" in aviso and "massagem" not in aviso.lower()
    # quem desliga os avisos não recebe mais
    a.post("/api/whats/avisos", json={"ligado": False})
    a.post("/api/sinal", json={"tema": "hotel", "estado": "vontade"})
    b.post("/api/sinal", json={"tema": "hotel", "estado": "vontade"})
    assert "novidade" in para("5562933334444")[-1] and sum("novidade" in t for t in para("5562911112222")) == 1


def test_desvincular(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    a = pessoa("ana@x.com", "Ana")
    msg(app, "5562911112222", a.post("/api/whats/codigo").json()["codigo"], "v")
    assert a.delete("/api/whats").json()["ok"]
    assert a.get("/api/whats").json()["vinculado"] is False
    msg(app, "5562911112222", "oi", "e9")
    assert "crie sua conta" in para("5562911112222")[-1]


def test_menor_nao_gera_codigo(amb):
    app, pessoa, adm = amb
    ligar_casa(adm)
    c = TestClient(app)
    entrar(c, "jovem@x.com")
    assert c.post("/api/whats/codigo").status_code == 403
