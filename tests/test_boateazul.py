import json
import os

os.environ["BOATE_SEM_APP"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import match  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import criar_app  # noqa: E402

VISTOS = []
SINAIS = {"sinais": []}


def llm_falso(msgs):
    VISTOS.append(msgs)
    if "Responda SÓ um JSON" in msgs[-1]["content"]:
        return json.dumps(SINAIS)
    return "Que bom que você me contou. Como vocês costumam fugir da rotina?"


@pytest.fixture
def amb(tmp_path):
    VISTOS.clear()
    cfg = Config(dados=str(tmp_path), segredo_sessao="s", dev=True, cakto_segredo="ck", planos_por_produto={"p-int": "intimo"})
    app = criar_app(cfg, llm=llm_falso)

    def pessoa(email, nome, nasc="1990-05-10"):
        c = TestClient(app)
        cod = c.post("/api/entrar/codigo", json={"email": email}).json()["codigo_dev"]
        assert c.post("/api/entrar", json={"email": email, "codigo": cod}).status_code == 200
        assert c.post("/api/perfil", json={"nome": nome, "nascimento": nasc, "limites": "nada com terceiros"}).status_code == 200
        return c
    return app, pessoa


def casar(a, b):
    cod = a.post("/api/casal/criar").json()["codigo"]
    r = b.post("/api/casal/entrar", json={"codigo": cod})
    assert r.status_code == 200, r.text
    return cod


def test_menor_de_idade_nao_entra(amb):
    app, pessoa = amb
    c = pessoa("ana@x.com", "Ana")
    assert c.post("/api/perfil", json={"nome": "Ju", "nascimento": "2012-01-01"}).status_code == 403


def test_match_so_aparece_com_os_dois_elegiveis(amb):
    app, pessoa = amb
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    casar(a, b)
    a.post("/api/sinal", json={"tema": "massagem", "estado": "vontade"})
    a.post("/api/sinal", json={"tema": "hotel", "estado": "interesse"})
    assert b.get("/api/nucleo").json()["matches"] == []  # só A marcou: nada aparece para ninguém
    b.post("/api/sinal", json={"tema": "hotel", "estado": "limite"})
    assert a.get("/api/nucleo").json()["matches"] == []  # limite nunca vira match nem aparece como "não"
    r = b.post("/api/sinal", json={"tema": "massagem", "estado": "curiosidade"}).json()
    assert r["revelados"] == 1
    for c in (a, b):
        n = c.get("/api/nucleo").json()
        assert [m["tema"] for m in n["matches"]] == ["massagem"] and len(n["missoes"]) == 1
        assert "hotel" not in json.dumps(n)  # o que não deu match não aparece


def test_privacidade_texto_de_a_nunca_vai_para_b(amb):
    app, pessoa = amb
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    casar(a, b)
    segredo = "SEGREDO-ANA: quero muito uma noite de striptease no aniversario"
    SINAIS["sinais"] = [{"tema": "striptease", "estado": "vontade"}]
    a.post("/api/conversa", json={"texto": segredo})
    import time
    time.sleep(0.3)  # extração de sinais roda em segundo plano
    SINAIS["sinais"] = []
    VISTOS.clear()
    b.post("/api/conversa", json={"texto": "oi, tudo bem?"})
    prompt_b = json.dumps(VISTOS, ensure_ascii=False)
    assert "SEGREDO-ANA" not in prompt_b and "aniversario" not in prompt_b
    # o tema pode ser sugerido, sem origem: aparece só o título, misturado com temas leves
    sugeridos = prompt_b.split("nunca crie expectativa): ")[1].split(".\n")[0]
    assert match.TEMAS["striptease"][1] in sugeridos and "," in sugeridos  # vem junto de outro tema (não entrega a origem)
    assert b.get("/api/conversa").json()["mensagens"][0]["texto"] == "oi, tudo bem?"  # B não vê a conversa de A


def test_pausar_some_o_nucleo_para_os_dois(amb):
    app, pessoa = amb
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    casar(a, b)
    for c in (a, b):
        c.post("/api/sinal", json={"tema": "date-night", "estado": "vontade"})
    assert len(a.get("/api/nucleo").json()["matches"]) == 1
    b.post("/api/casal/pausar")
    assert a.get("/api/nucleo").json()["matches"] == [] and b.get("/api/nucleo").json()["matches"] == []
    a.post("/api/casal/retomar")
    assert len(b.get("/api/nucleo").json()["matches"]) == 1
    a.post("/api/casal/desvincular")
    assert b.get("/api/conta").json()["casal"] is None


def test_plano_vale_para_o_casal_e_cakto(amb):
    app, pessoa = amb
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    casar(a, b)
    assert b.post("/api/sinal", json={"tema": "roleplay", "estado": "vontade"}).status_code == 402
    c = TestClient(app)
    r = c.post("/api/cakto", json={"secret": "ck", "event": "purchase_approved", "data": {"id": "p1", "customer": {"email": "ana@x.com"}, "product": {"id": "p-int"}}})
    assert r.json()["liberado"] == "ana@x.com"
    assert b.get("/api/conta").json()["plano"] == "intimo"  # quem não pagou também tem, porque é do casal
    assert b.post("/api/sinal", json={"tema": "roleplay", "estado": "vontade"}).status_code == 200


def test_checkin_mostra_so_a_media(amb):
    app, pessoa = amb
    a, b = pessoa("ana@x.com", "Ana"), pessoa("beto@x.com", "Beto")
    casar(a, b)
    assert a.post("/api/checkin", json={"conexao": 5}).json()["media_casal"] is None
    assert b.post("/api/checkin", json={"conexao": 3}).json()["media_casal"] == 4.0


def test_temas_tem_40_e_paginas_abrem(amb):
    app, pessoa = amb
    c = TestClient(app)
    t = c.get("/api/temas").json()
    assert sum(len(x["temas"]) for x in t["categorias"]) == 40 and len(t["categorias"]) == 6
    for p in ("/", "/app", "/admin", "/health"):
        assert c.get(p).status_code == 200
