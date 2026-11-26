"""Boate Azul: IA de desejo e intimidade para casais (+18). Spec 45 §G.

Cada pessoa conversa em particular com a própria IA (memória e sinais só dela). O casal vê só o Núcleo: afinidades que
os DOIS marcaram (match bilateral, app/match.py) e as missões que nascem delas. A IA de um nunca diz o que o outro falou;
ela pode puxar um tema de forma natural (lista de temas a explorar, sem texto nem origem, misturada com temas leves).
IA pelo Hermes dos produtos (regra do Lucas). Skill editável no /admin (skills/boate-azul.md).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import admin, auth, mailer, match, senha_rotas, whats
from produtos_core import acesso, armazenamento
from app.config import Config, carregar
from app.db import Banco, agora

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("boateazul")
COOKIE = "boateazul_s"
ESTATICO = Path(__file__).resolve().parent.parent / "static"
GRATIS_MSGS_DIA = 15
MEMORIA_A_CADA = 4

PLANOS = {
    "essencial": {"nome": "Essencial", "preco": 29.90, "itens": ["Explorar afinidades e Núcleo do Casal", "Matches básicos", "Check-in semanal"]},
    "conexao": {"nome": "Conexão", "preco": 59.90, "itens": ["Tudo do Essencial", "Assistente privado sem limite, que lembra de tudo", "Missões do casal toda semana"]},
    "intimo": {"nome": "Íntimo", "preco": 99.90, "itens": ["Tudo do Conexão", "Programas de intimidade +18 personalizados", "Fantasias e jogos liberados", "Acompanhamento aprofundado"]},
}

CABECA = """Você é a assistente privada da Boate Azul, uma IA de relacionamento e intimidade para casais adultos (+18).
Siga a skill boate-azul abaixo em tudo.
=== SKILL boate-azul ===
{skill}
=== FIM DA SKILL ===
CONTEXTO DESTA PESSOA (privado, só dela):
{contexto}"""
RESUMIR = """Você mantém a memória privada de uma assistente de relacionamento sobre UMA pessoa.
Reescreva a MEMÓRIA com o que importa para as próximas conversas: nome do(a) parceiro(a), fase da relação, rotina,
o que a pessoa quer viver, o que a incomoda, desejos, curiosidades, limites, datas importantes. Tópicos curtos, no máximo
25 linhas. Responda só com a memória."""
EXTRAIR = """Leia a mensagem de uma pessoa sobre a vida a dois e marque SÓ os temas que ela expressou claramente.
Temas possíveis (id: título): {temas}
Estados: vontade (deseja claramente), interesse (abertura positiva), curiosidade (quer conhecer), talvez (não agora),
sem_interesse, limite (não quer de jeito nenhum).
Responda SÓ um JSON: {{"sinais": [{{"tema": "<id>", "estado": "<estado>"}}]}} (lista vazia se nada claro).
Mensagem: {texto}"""


def criar_app(cfg: Config | None = None, llm=None, gateway: whats.Gateway | None = None) -> FastAPI:
    cfg = cfg or carregar()
    os.makedirs(cfg.dados, exist_ok=True)
    db = Banco(os.path.join(cfg.dados, "boateazul.db"))
    admin.preparar(db)
    app = FastAPI(title="Boate Azul", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.db = cfg, db
    gw = gateway or whats.Gateway(cfg.canais_url, cfg.canais_token)

    def chamar_llm(mensagens: list[dict], max_tokens: int = 900, temperatura: float = 0.85) -> str:
        if llm:
            return llm(mensagens)
        r = httpx.post(cfg.llm_base + "/chat/completions", headers={"Authorization": f"Bearer {cfg.llm_key}"}, timeout=180,
                       json={"model": cfg.llm_modelo, "messages": mensagens, "temperature": temperatura, "max_tokens": max_tokens})
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()

    if cfg.demo_email:
        u = auth.usuario_por_email(db, cfg.demo_email.lower())
        db.exec("INSERT INTO assinaturas(usuario,plano,ativo_ate) VALUES(?,?,?) ON CONFLICT(usuario) DO UPDATE SET plano=excluded.plano, ativo_ate=excluded.ativo_ate",
                (u["id"], "intimo", agora() + 3650 * 86400))

    # ------------------------------------------------ ajudantes
    def usuario(request: Request, obrigatorio: bool = True) -> dict | None:
        u = auth.usuario_da_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        if not u and obrigatorio:
            raise HTTPException(401, "entre na sua conta")
        return u

    def casal_de(uid: int) -> dict | None:
        return db.um("SELECT c.* FROM casais c JOIN membros m ON m.casal=c.id WHERE m.usuario=? AND c.estado<>'encerrado'", (uid,))

    def plano_de(u: dict) -> str | None:
        """O plano vale para o casal: basta um dos dois ter assinatura ativa (com vínculo ativo)."""
        ids = [u["id"]]
        c = casal_de(u["id"])
        if c and c["estado"] == "ativo":
            ids = [m["usuario"] for m in db.todos("SELECT usuario FROM membros WHERE casal=?", (c["id"],))]
        melhor = None
        for i in ids:
            a = db.um("SELECT * FROM assinaturas WHERE usuario=?", (i,))
            if a and a["ativo_ate"] > agora():
                if not melhor or list(PLANOS).index(a["plano"]) > list(PLANOS).index(melhor):
                    melhor = a["plano"]
        return melhor

    def perfil(uid: int) -> dict:
        return db.um("SELECT * FROM perfis WHERE usuario=?", (uid,)) or {"nome": "", "nascimento": "", "fase": "", "objetivos": "", "limites": "", "afeto": "", "tom": ""}

    def maior_de_idade(nasc: str) -> bool:
        try:
            d = dt.date.fromisoformat(nasc)
        except (TypeError, ValueError):
            return False
        h = dt.date.today()
        return (h.year - d.year - ((h.month, h.day) < (d.month, d.day))) >= 18

    def exigir_adulto(u: dict) -> None:
        if not maior_de_idade(perfil(u["id"]).get("nascimento", "")):
            raise HTTPException(403, "conteúdo só para maiores de 18 anos: informe a sua data de nascimento no perfil")

    def hoje_ini() -> float:
        h = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3)))
        return h.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def nome_parceiro(uid: int, c: dict | None) -> str:
        if not c:
            return ""
        o = db.um("SELECT usuario FROM membros WHERE casal=? AND usuario<>?", (c["id"], uid))
        return (perfil(o["usuario"])["nome"] if o else "") or ""

    def contexto(u: dict) -> str:
        p = perfil(u["id"])
        c = casal_de(u["id"])
        mem = db.um("SELECT texto FROM memorias WHERE usuario=?", (u["id"],))
        meus = db.todos("SELECT tema, estado FROM sinais WHERE usuario=?", (u["id"],))
        explorar = match.temas_para_explorar(db, u["id"], c)
        vinculo = {"ativo": "vinculado(a) ao parceiro(a)", "aguardando": "convite enviado, parceiro(a) ainda não entrou",
                   "pausado": "vínculo pausado"}.get(c["estado"], "sem vínculo") if c else "sem vínculo"
        return (f"Nome: {p['nome'] or '(não informou)'}. Parceiro(a): {nome_parceiro(u['id'], c) or '(não informado)'}. Vínculo: {vinculo}.\n"
                f"Fase da relação: {p['fase'] or '?'}. Objetivos: {p['objetivos'] or '?'}. Linguagem de afeto: {p['afeto'] or '?'}.\n"
                f"LIMITES desta pessoa (respeite sempre): {p['limites'] or 'não informou'}.\n"
                f"Tom preferido: {p['tom'] or 'leve e acolhedor'}. Plano: {plano_de(u) or 'grátis'}.\n"
                f"O que esta pessoa já marcou: {', '.join(match.TEMAS[s['tema']][1] + '=' + s['estado'] for s in meus if s['tema'] in match.TEMAS) or 'nada ainda'}.\n"
                f"Temas que você PODE puxar naturalmente nesta conversa, se couber (nunca diga de onde veio a ideia, nunca diga que o "
                f"parceiro marcou nada, nunca crie expectativa): {', '.join(explorar) or 'nenhum por enquanto'}.\n"
                f"MEMÓRIA (o que você já sabe desta pessoa):\n{mem['texto'] if mem else 'Ainda nada: é o começo.'}")

    def sistema(u: dict) -> str:
        return CABECA.format(skill=admin.skill(db, "boate-azul"), contexto=contexto(u))

    def extrair_sinais(uid: int, texto: str) -> list[str]:
        """Lê a mensagem e marca sinais privados (só de quem escreveu). Depois tenta revelar matches."""
        try:
            temas = "; ".join(f"{k}: {v[1]}" for k, v in match.TEMAS.items())
            out = chamar_llm([{"role": "user", "content": EXTRAIR.format(temas=temas, texto=texto[:1500])}], 400, 0.1)
            m = re.search(r"\{.*\}", out, re.S)
            sinais = (json.loads(m.group(0)).get("sinais") if m else []) or []
        except Exception:  # noqa: BLE001
            log.exception("sinais não extraídos")
            return []
        for s in sinais:
            t, e = str(s.get("tema") or ""), str(s.get("estado") or "")
            if t in match.TEMAS and e in match.ESTADOS:
                db.exec("INSERT INTO sinais(usuario,tema,estado,origem,atualizado) VALUES(?,?,?,?,?) ON CONFLICT(usuario,tema) DO UPDATE SET estado=excluded.estado, origem=excluded.origem, atualizado=excluded.atualizado",
                        (uid, t, e, "conversa", agora()))
        return revelar(casal_de(uid) or {})

    def atualizar_memoria(uid: int) -> None:
        try:
            mem = db.um("SELECT texto FROM memorias WHERE usuario=?", (uid,))
            hist = db.todos("SELECT papel, texto FROM mensagens WHERE usuario=? ORDER BY criado DESC, id DESC LIMIT 24", (uid,))[::-1]
            conversa = "\n".join(f"{'Pessoa' if m['papel'] == 'usuario' else 'Assistente'}: {m['texto'][:600]}" for m in hist)
            novo = chamar_llm([{"role": "system", "content": RESUMIR},
                               {"role": "user", "content": f"MEMÓRIA ATUAL:\n{mem['texto'] if mem else '(vazia)'}\n\nCONVERSA RECENTE:\n{conversa}"}], 900, 0.3)
            if novo.strip():
                db.exec("INSERT INTO memorias(usuario,texto,atualizado) VALUES(?,?,?) ON CONFLICT(usuario) DO UPDATE SET texto=excluded.texto, atualizado=excluded.atualizado",
                        (uid, novo.strip()[:8000], agora()))
        except Exception:  # noqa: BLE001
            log.exception("memória não atualizada")

    # ------------------------------------------------ WhatsApp (spec 59)
    def casa() -> dict | None:
        return db.um("SELECT * FROM whats_casa WHERE id=1")

    def whats_enviar(conversa: str, texto: str, chave: str) -> bool:
        k = casa()
        if not k or k["estado"] != "connected":
            return False
        try:
            gw.enviar(k["conexao"], conversa, texto, chave)
            return True
        except whats.CanalErro as e:
            log.warning("whats não enviado: %s", e)
            return False

    def revelar(casal: dict) -> list[str]:
        """Revela matches novos e avisa os DOIS no WhatsApp, sem dizer o tema (a tela pode estar à vista)."""
        novos = match.revelar(db, casal)
        if novos:
            for m in db.todos("SELECT w.usuario, w.conversa FROM whats_vinculos w JOIN membros m ON m.usuario=w.usuario WHERE m.casal=? AND w.avisos=1 AND w.conversa IS NOT NULL", (casal["id"],)):
                whats_enviar(m["conversa"], f"Vocês têm novidade no Núcleo do casal. Abra o app para ver: {cfg.base_url}/app",
                             f"nucleo:{casal['id']}:{m['usuario']}:{','.join(novos)}")
        return novos

    def responder(u: dict, texto: str) -> str:
        """A conversa privada (app e WhatsApp usam a mesma): limites do plano, IA, memória e sinais."""
        exigir_adulto(u)
        texto = texto.strip()[:3000]
        if not texto:
            raise HTTPException(422, "escreva a mensagem")
        if plano_de(u) not in ("conexao", "intimo"):
            hoje = db.um("SELECT COUNT(*) n FROM mensagens WHERE usuario=? AND papel='usuario' AND criado>?", (u["id"], hoje_ini()))["n"]
            if hoje >= GRATIS_MSGS_DIA:
                raise HTTPException(402, f"no plano grátis são {GRATIS_MSGS_DIA} mensagens por dia; no Conexão a conversa é sem limite")
        hist = db.todos("SELECT papel, texto FROM mensagens WHERE usuario=? ORDER BY criado DESC, id DESC LIMIT 16", (u["id"],))[::-1]
        msgs = [{"role": "system", "content": sistema(u)}] + [{"role": "user" if m["papel"] == "usuario" else "assistant", "content": m["texto"]} for m in hist]
        msgs.append({"role": "user", "content": texto})
        try:
            resposta = chamar_llm(msgs, 1100)
        except Exception:  # noqa: BLE001
            log.exception("IA fora")
            raise HTTPException(503, "a assistente está ocupada agora; tente de novo em instantes")
        db.exec("INSERT INTO mensagens(usuario,papel,texto,criado) VALUES(?,?,?,?)", (u["id"], "usuario", texto, agora()))
        db.exec("INSERT INTO mensagens(usuario,papel,texto,criado) VALUES(?,?,?,?)", (u["id"], "ia", resposta, agora() + 0.001))
        n = db.um("SELECT COUNT(*) n FROM mensagens WHERE usuario=? AND papel='usuario'", (u["id"],))["n"]
        threading.Thread(target=extrair_sinais, args=(u["id"], texto), daemon=True).start()
        if n % MEMORIA_A_CADA == 0:
            threading.Thread(target=atualizar_memoria, args=(u["id"],), daemon=True).start()
        return resposta

    @app.exception_handler(json.JSONDecodeError)
    async def corpo_invalido(request: Request, exc: Exception):
        return JSONResponse({"detail": "corpo inválido (envie JSON)"}, status_code=400)

    @app.get("/health")
    def health():
        return {"ok": True}

    # ------------------------------------------------ login (mesmo padrão dos outros produtos)
    def _login(u: dict) -> JSONResponse:
        token = auth.criar_sessao(db, cfg.segredo_sessao, u["id"])
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, token, max_age=auth.SESSAO_S, httponly=True, secure=not cfg.dev, samesite="lax", path="/")
        return resp

    acesso.registrar(app, db, enviar=lambda para, assunto, texto, html: mailer.enviar(cfg, para, assunto, texto, html),
                     login=_login, usuario=usuario, criar_usuario=lambda email: auth.usuario_por_email(db, email),
                     produto="Boate Azul", base_url=cfg.base_url, destino="/app", cor="#7c5cff",
                     demo_email=lambda: cfg.demo_email, demo_senha=lambda: cfg.demo_senha, dev=cfg.dev)  # cadastro e login comuns (spec 57 §5A)
    armazenamento.registrar(app, armazenamento.Armazenamento(pasta_local=os.path.join(getattr(cfg, "dados", "") or ".", "arquivos")))  # MinIO (spec 57 §8.6)

    @app.post("/api/sair")
    def sair(request: Request):
        auth.encerrar_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    # ------------------------------------------------ público
    @app.get("/api/planos")
    def planos():
        return {"planos": [{"id": k, **v, "checkout": cfg.checkouts.get(k, "")} for k, v in PLANOS.items()]}

    @app.get("/api/temas")
    def temas(request: Request):
        u = usuario(request, obrigatorio=False)
        meus = {s["tema"]: s["estado"] for s in db.todos("SELECT tema, estado FROM sinais WHERE usuario=?", (u["id"],))} if u else {}
        cats = []
        for cid, cnome in match.CATEGORIAS.items():
            cats.append({"id": cid, "nome": cnome, "temas": [{"id": t, "titulo": v[1], "leve": v[2], "meu": meus.get(t)}
                                                            for t, v in match.TEMAS.items() if v[0] == cid]})
        return {"categorias": cats, "estados": match.ESTADOS}

    # ------------------------------------------------ conta, perfil e vínculo
    @app.get("/api/conta")
    def conta(request: Request):
        u = usuario(request)
        c = casal_de(u["id"])
        p = perfil(u["id"])
        return {"email": u["email"], "plano": plano_de(u), "perfil": {k: p.get(k, "") for k in ("nome", "nascimento", "fase", "objetivos", "limites", "afeto", "tom")},
                "adulto": maior_de_idade(p.get("nascimento", "")),
                "casal": ({"estado": c["estado"], "codigo": c["codigo"] if c["estado"] == "aguardando" else None,
                           "parceiro": nome_parceiro(u["id"], c)} if c else None)}

    @app.post("/api/perfil")
    async def salvar_perfil(request: Request):
        u = usuario(request)
        b = await request.json()
        campos = {k: str(b.get(k) or "").strip()[:600] for k in ("nome", "nascimento", "fase", "objetivos", "limites", "afeto", "tom")}
        if campos["nascimento"] and not maior_de_idade(campos["nascimento"]):
            raise HTTPException(403, "a Boate Azul é só para maiores de 18 anos")
        db.exec("""INSERT INTO perfis(usuario,nome,nascimento,fase,objetivos,limites,afeto,tom,atualizado) VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(usuario) DO UPDATE SET nome=excluded.nome, nascimento=excluded.nascimento, fase=excluded.fase,
                   objetivos=excluded.objetivos, limites=excluded.limites, afeto=excluded.afeto, tom=excluded.tom, atualizado=excluded.atualizado""",
                (u["id"], *campos.values(), agora()))
        return {"ok": True}

    @app.post("/api/casal/criar")
    def casal_criar(request: Request):
        u = usuario(request)
        if casal_de(u["id"]):
            raise HTTPException(409, "você já tem um vínculo; desvincule antes de criar outro")
        cod = secrets.token_hex(3).upper()
        cid = db.exec("INSERT INTO casais(codigo,criado) VALUES(?,?)", (cod, agora())).lastrowid
        db.exec("INSERT INTO membros(casal,usuario,entrou) VALUES(?,?,?)", (cid, u["id"], agora()))
        return {"codigo": cod, "link": f"{cfg.base_url}/?convite={cod}"}

    @app.post("/api/casal/entrar")
    async def casal_entrar(request: Request):
        u = usuario(request)
        b = await request.json()
        cod = str(b.get("codigo") or "").strip().upper()
        c = db.um("SELECT * FROM casais WHERE codigo=? AND estado='aguardando'", (cod,))
        if not c:
            raise HTTPException(404, "convite não encontrado ou já usado")
        if casal_de(u["id"]):
            raise HTTPException(409, "você já tem um vínculo; desvincule antes de entrar em outro")
        if db.um("SELECT 1 FROM membros WHERE casal=? AND usuario=?", (c["id"], u["id"])):
            raise HTTPException(409, "este é o seu próprio convite: mande o link para o(a) parceiro(a)")
        db.exec("INSERT INTO membros(casal,usuario,entrou) VALUES(?,?,?)", (c["id"], u["id"], agora()))
        db.exec("UPDATE casais SET estado='ativo' WHERE id=?", (c["id"],))
        novos = revelar(casal_de(u["id"]))
        return {"ok": True, "revelados": len(novos)}

    @app.post("/api/casal/{acao}")
    def casal_acao(acao: str, request: Request):
        u = usuario(request)
        c = casal_de(u["id"])
        if not c:
            raise HTTPException(404, "sem vínculo")
        if acao == "pausar" and c["estado"] == "ativo":
            db.exec("UPDATE casais SET estado='pausado' WHERE id=?", (c["id"],))
        elif acao == "retomar" and c["estado"] == "pausado":
            db.exec("UPDATE casais SET estado='ativo' WHERE id=?", (c["id"],))
            revelar(casal_de(u["id"]))
        elif acao == "desvincular":
            # encerra para os dois; o núcleo some. As conversas e sinais privados continuam de cada um.
            db.exec("UPDATE casais SET estado='encerrado' WHERE id=?", (c["id"],))
            db.exec("DELETE FROM membros WHERE casal=?", (c["id"],))
        else:
            raise HTTPException(400, "ação inválida")
        return {"ok": True}

    # ------------------------------------------------ afinidades (cartões privados) e núcleo do casal
    @app.post("/api/sinal")
    async def sinal(request: Request):
        u = usuario(request)
        exigir_adulto(u)
        b = await request.json()
        t, e = str(b.get("tema") or ""), str(b.get("estado") or "")
        if t not in match.TEMAS or e not in match.ESTADOS:
            raise HTTPException(422, "tema ou estado inválido")
        if not match.TEMAS[t][2] and (plano_de(u) or "") not in ("intimo",) and match.TEMAS[t][0] == "fantasias":
            # fantasias ficam no plano Íntimo (os outros temas são livres para marcar)
            raise HTTPException(402, "fantasias e jogos fazem parte do plano Íntimo")
        db.exec("INSERT INTO sinais(usuario,tema,estado,origem,atualizado) VALUES(?,?,?,?,?) ON CONFLICT(usuario,tema) DO UPDATE SET estado=excluded.estado, origem=excluded.origem, atualizado=excluded.atualizado",
                (u["id"], t, e, "cartao", agora()))
        novos = revelar(casal_de(u["id"]) or {})
        return {"ok": True, "revelados": len(novos)}

    @app.get("/api/nucleo")
    def nucleo(request: Request):
        u = usuario(request)
        c = casal_de(u["id"])
        if not c or c["estado"] != "ativo":
            return {"estado": c["estado"] if c else "sem_vinculo", "matches": [], "missoes": []}
        ms = db.todos("SELECT tema, nivel, criado FROM matches WHERE casal=? ORDER BY criado DESC", (c["id"],))
        mi = db.todos("SELECT id, tema, tipo, titulo, texto, estado, criado FROM missoes WHERE casal=? ORDER BY estado, criado DESC", (c["id"],))
        frase = {"afinidade": "Vocês têm isso em comum", "conversar": "Vocês dois querem conversar sobre isso",
                 "experiencia": "Vocês dois querem viver isso", "objetivo": "Um objetivo dos dois"}
        return {"estado": "ativo", "parceiro": nome_parceiro(u["id"], c),
                "matches": [{"tema": m["tema"], "titulo": match.TEMAS[m["tema"]][1], "categoria": match.CATEGORIAS[match.TEMAS[m["tema"]][0]],
                             "nivel": match.NIVEIS[m["nivel"]], "frase": frase[m["nivel"]], "criado": m["criado"]} for m in ms if m["tema"] in match.TEMAS],
                "missoes": mi}

    @app.post("/api/missao/{mid}/concluir")
    def missao_concluir(mid: int, request: Request):
        u = usuario(request)
        c = casal_de(u["id"])
        m = db.um("SELECT * FROM missoes WHERE id=?", (mid,))
        if not c or not m or m["casal"] != c["id"]:
            raise HTTPException(404, "missão não encontrada")
        db.exec("UPDATE missoes SET estado='concluida', concluida=? WHERE id=?", (agora(), mid))
        return {"ok": True}

    @app.post("/api/checkin")
    async def checkin(request: Request):
        u = usuario(request)
        b = await request.json()
        n = int(b.get("conexao") or 0)
        if not 1 <= n <= 5:
            raise HTTPException(422, "conexão de 1 a 5")
        c = casal_de(u["id"])
        db.exec("INSERT INTO checkins(usuario,casal,conexao,prioridade,criado) VALUES(?,?,?,?,?)",
                (u["id"], c["id"] if c else None, n, str(b.get("prioridade") or "")[:300], agora()))
        # o casal vê só a média da semana, nunca a nota de cada um
        media = None
        if c and c["estado"] == "ativo":
            r = db.um("SELECT AVG(conexao) m, COUNT(DISTINCT usuario) q FROM checkins WHERE casal=? AND criado>?", (c["id"], agora() - 7 * 86400))
            media = round(r["m"], 1) if r and r["q"] == 2 else None
        return {"ok": True, "media_casal": media}

    # ------------------------------------------------ conversa privada
    @app.get("/api/conversa")
    def historico(request: Request):
        u = usuario(request)
        return {"mensagens": db.todos("SELECT papel, texto, criado FROM mensagens WHERE usuario=? ORDER BY criado, id LIMIT 300", (u["id"],))}

    @app.post("/api/conversa")
    async def conversar(request: Request):
        u = usuario(request)
        b = await request.json()
        return {"resposta": await run_in_threadpool(responder, u, str(b.get("texto") or ""))}

    # ------------------------------------------------ WhatsApp: vínculo de cada pessoa (spec 59)
    def numero_casa() -> str:
        k = casa()
        return (k["numero"] if k and k["numero"] else "") or cfg.whats_numero

    @app.get("/api/whats")
    def whats_meu(request: Request):
        u = usuario(request)
        v = db.um("SELECT * FROM whats_vinculos WHERE usuario=?", (u["id"],))
        k = casa()
        return {"disponivel": bool(k and k["estado"] == "connected" and numero_casa()), "vinculado": bool(v and v["conversa"]),
                "numero": whats.mascarar(v["numero"]) if v else "", "avisos": bool(v["avisos"]) if v else True}

    @app.post("/api/whats/codigo")
    def whats_codigo(request: Request):
        u = usuario(request)
        exigir_adulto(u)
        n = numero_casa()
        if not n:
            raise HTTPException(503, "o WhatsApp da Boate Azul ainda não está ligado; tente mais tarde")
        cod = whats.novo_codigo(db, u["id"], agora())
        return {"codigo": cod, "link": f"https://wa.me/{n}?text={cod}", "vale_min": whats.CODIGO_VALE_S // 60}

    @app.post("/api/whats/avisos")
    async def whats_avisos(request: Request):
        u = usuario(request)
        b = await request.json()
        db.exec("UPDATE whats_vinculos SET avisos=? WHERE usuario=?", (1 if b.get("ligado") else 0, u["id"]))
        return {"ok": True}

    @app.delete("/api/whats")
    def whats_desvincular(request: Request):
        u = usuario(request)
        db.exec("DELETE FROM whats_vinculos WHERE usuario=?", (u["id"],))
        db.exec("DELETE FROM whats_codigos WHERE usuario=?", (u["id"],))
        return {"ok": True}

    def tratar_whats(conversa: str, numero: str, texto: str, chave: str) -> None:
        """Mensagem que chegou no número da casa: vínculo por código, conversa privada ou convite para o cadastro."""
        v = db.um("SELECT * FROM whats_vinculos WHERE conversa=?", (conversa,))
        dono = whats.dono_do_codigo(db, texto, agora())
        if dono and not v:
            if numero and db.um("SELECT 1 FROM whats_vinculos WHERE numero=? AND usuario<>?", (numero, dono)):
                whats_enviar(conversa, "Este número já está vinculado a outra conta da Boate Azul.", chave + ":r")
                return
            db.exec("INSERT INTO whats_vinculos(usuario,conversa,numero,avisos,vinculado) VALUES(?,?,?,1,?) ON CONFLICT(usuario) DO UPDATE SET conversa=excluded.conversa, numero=excluded.numero, vinculado=excluded.vinculado",
                    (dono, conversa, numero, agora()))
            db.exec("DELETE FROM whats_codigos WHERE usuario=?", (dono,))
            nome = perfil(dono)["nome"] or ""
            whats_enviar(conversa, f"Pronto{', ' + nome if nome else ''}! Seu WhatsApp está vinculado. Pode conversar comigo por aqui: "
                         "é a mesma conversa privada do app, só sua.", chave + ":r")
            return
        if not v:
            whats_enviar(conversa, f"Oi! Aqui é a Boate Azul. Para conversar por aqui, crie sua conta em {cfg.base_url} e toque em "
                         "\"Vincular meu WhatsApp\" no app.", chave + ":r")
            return
        if dono:  # mandou um código, mas este WhatsApp já está vinculado
            whats_enviar(conversa, "Este WhatsApp já está vinculado. Pode conversar comigo normalmente.", chave + ":r")
            return
        u = db.um("SELECT * FROM usuarios WHERE id=?", (v["usuario"],))
        if not u:
            return
        try:
            resposta = responder(u, texto)
        except HTTPException as e:
            resposta = f"{e.detail[:1].upper()}{e.detail[1:]}. {cfg.base_url}/app"
        whats_enviar(conversa, resposta, chave + ":r")

    @app.post("/hooks/whats")
    async def webhook_whats(request: Request, tarefas: BackgroundTasks):
        k = casa()
        corpo = await request.body()
        if not k or not whats.assinatura_ok(k["segredo"], request.headers.get("x-luar-timestamp", ""), request.headers.get("x-luar-signature", ""), corpo):
            raise HTTPException(401, "assinatura")
        ev = json.loads(corpo)
        eid = str(ev.get("event_id") or request.headers.get("x-luar-event-id") or "")
        if eid:
            if db.um("SELECT 1 FROM whats_eventos WHERE id=?", (eid,)):
                return {"ok": True, "repetido": True}
            db.exec("INSERT INTO whats_eventos(id,recebido) VALUES(?,?)", (eid, agora()))
        tipo = ev.get("type")
        if tipo == "connection.state":
            st = (ev.get("state") or {}).get("state")
            if st:
                db.exec("UPDATE whats_casa SET estado=?, atualizado=? WHERE id=1", (st, agora()))
            return {"ok": True}
        if tipo != "message.created":
            return {"ok": True, "ignorado": tipo}
        conv, msg = ev.get("conversation") or {}, ev.get("message") or {}
        externo = str(conv.get("external_id") or "")
        if not externo or msg.get("direction") == "outgoing_echo":
            return {"ok": True, "ignorado": "eco ou sem conversa"}
        texto = str(msg.get("text") or "").strip() or "[a pessoa mandou um anexo]"
        tarefas.add_task(tratar_whats, externo, whats.numero_de(conv), texto, "msg:" + str(msg.get("external_id") or eid))
        return {"ok": True}

    # ------------------------------------------------ WhatsApp da casa (/admin)
    def vista_casa(view: dict | None = None) -> dict:
        k = casa()
        out = {"estado": k["estado"] if k else "desligado", "numero": whats.mascarar(k["numero"]) if k and k["numero"] else "",
               "vinculados": db.um("SELECT COUNT(*) n FROM whats_vinculos WHERE conversa IS NOT NULL")["n"]}
        passo = (view or {}).get("step") or {}
        if passo:
            out["qr"] = (passo.get("qr") or {}).get("data")
            out["codigo_pareamento"] = passo.get("pairing_code")
        return out

    def atualizar_casa(view: dict) -> None:
        con = view.get("connection") or view
        numero = re.sub(r"\D", "", str(con.get("external_label") or ""))
        db.exec("UPDATE whats_casa SET estado=?, numero=CASE WHEN ?<>'' THEN ? ELSE numero END, atualizado=? WHERE id=1",
                (con.get("state") or "pending_auth", numero, numero, agora()))

    def rotas_whats_admin(checar) -> None:
        @app.get("/api/painel/whats")
        def admin_whats(request: Request):
            checar(request)
            k = casa()
            view = None
            if k and k["estado"] != "connected":
                try:
                    view = gw.status(k["conexao"])
                    atualizar_casa(view)
                except whats.CanalErro as e:
                    log.warning("status da casa: %s", e)
            return vista_casa(view)

        @app.post("/api/painel/whats/conectar")
        def admin_whats_conectar(request: Request):
            checar(request)
            try:
                view = gw.conectar()
            except whats.CanalErro as e:
                raise HTTPException(502, f"gateway: {e.codigo}")
            con = view.get("connection") or view
            segredo = secrets.token_urlsafe(32)
            db.exec("DELETE FROM whats_casa WHERE id=1")
            db.exec("INSERT INTO whats_casa(id,conexao,estado,numero,segredo,atualizado) VALUES(1,?,?,'',?,?)",
                    (con["id"], con.get("state") or "pending_auth", segredo, agora()))
            try:
                gw.entrega(con["id"], f"{cfg.webhook_base}/hooks/whats", segredo)
            except whats.CanalErro as e:
                raise HTTPException(502, f"gateway (entrega): {e.codigo}")
            atualizar_casa(view)
            return vista_casa(view)

        @app.post("/api/painel/whats/desconectar")
        def admin_whats_desconectar(request: Request):
            checar(request)
            k = casa()
            if k:
                try:
                    gw.acao(k["conexao"], "disconnect")
                except whats.CanalErro as e:
                    log.warning("desconectar casa: %s", e)
                db.exec("UPDATE whats_casa SET estado='disconnected', atualizado=? WHERE id=1", (agora(),))
            return vista_casa()

    # ------------------------------------------------ Cakto (assinatura por casal)
    @app.post("/api/cakto")
    async def cakto(request: Request):
        cru = await request.body()
        try:
            b = json.loads(cru)
        except ValueError:
            raise HTTPException(400, "json")
        if not cfg.cakto_segredo or not hmac.compare_digest(str(b.get("secret") or ""), cfg.cakto_segredo):
            raise HTTPException(401, "segredo")
        evento = str(b.get("event") or "")
        dados = b.get("data") or {}
        if isinstance(dados, list):
            dados = dados[0] if dados else {}
        eid = str(dados.get("id") or hashlib.sha256(cru).hexdigest()[:24]) + ":" + evento
        if db.um("SELECT 1 FROM eventos_cakto WHERE id=?", (eid,)):
            return {"ok": True, "repetido": True}
        db.exec("INSERT INTO eventos_cakto(id,recebido,corpo) VALUES(?,?,?)", (eid, agora(), cru.decode("utf-8", "replace")[:20000]))
        email = auth.normalizar_email((dados.get("customer") or {}).get("email"))
        plano = cfg.planos_por_produto.get(str((dados.get("product") or {}).get("id") or ""))
        if not email or plano not in PLANOS:
            return {"ok": True, "ignorado": "sem email ou produto desconhecido"}
        u = auth.usuario_por_email(db, email)
        a = db.um("SELECT * FROM assinaturas WHERE usuario=?", (u["id"],))
        if evento in ("purchase_approved", "subscription_renewed", "subscription_created"):
            base = max(agora(), a["ativo_ate"] if a else 0)
            db.exec("INSERT INTO assinaturas(usuario,plano,ativo_ate,pedido) VALUES(?,?,?,?) ON CONFLICT(usuario) DO UPDATE SET plano=excluded.plano, ativo_ate=excluded.ativo_ate, pedido=excluded.pedido",
                    (u["id"], plano, base + 32 * 86400, str(dados.get("id") or "")))
            return {"ok": True, "liberado": email}
        if evento in ("refund", "chargeback", "subscription_canceled", "subscription_cancelled"):
            db.exec("UPDATE assinaturas SET ativo_ate=? WHERE usuario=?", (agora(), u["id"]))
            return {"ok": True, "revogado": email}
        return {"ok": True, "ignorado": evento}

    # ------------------------------------------------ páginas
    rotas_admin = admin.rotas(db, cfg.segredo_sessao, """SELECT u.email, u.criado, a.plano, a.ativo_ate, (a.ativo_ate > strftime('%s','now')) ativo
        FROM usuarios u LEFT JOIN assinaturas a ON a.usuario=u.id ORDER BY u.criado DESC""", seguro=not cfg.dev)
    rotas_whats_admin(rotas_admin.checar)
    app.include_router(rotas_admin)

    @app.get("/admin", response_class=HTMLResponse)
    def pagina_admin():
        return FileResponse(ESTATICO / "admin.html")

    app.mount("/s", StaticFiles(directory=ESTATICO), name="estatico")

    @app.get("/", response_class=HTMLResponse)
    def inicio():
        return FileResponse(ESTATICO / "index.html")

    @app.get("/app", response_class=HTMLResponse)
    def painel():
        return FileResponse(ESTATICO / "painel.html")

    return app


app = criar_app() if os.environ.get("BOATE_SEM_APP") != "1" else None
