"""Banco da Boate Azul: SQLite num volume (/data). Hora em epoch (s).

Privacidade é estrutural: tudo que a pessoa conta (mensagens, memória, sinais) é por `usuario`; o casal só enxerga
`matches` e `missoes`, que só nascem quando os DOIS marcaram o mesmo tema como elegível (app/match.py).
"""
from __future__ import annotations

import os
import sqlite3
import uuid
import threading
import time
from contextlib import contextmanager

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, criado REAL NOT NULL,
  plano TEXT NOT NULL DEFAULT 'teste', ativo_ate REAL NOT NULL DEFAULT 0, pedido TEXT);
CREATE TABLE IF NOT EXISTS codigos (email TEXT PRIMARY KEY, hash TEXT NOT NULL, expira REAL NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0, enviado REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessoes (hash TEXT PRIMARY KEY, usuario INTEGER NOT NULL, expira REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eventos_cakto (id TEXT PRIMARY KEY, recebido REAL NOT NULL, corpo TEXT NOT NULL);
-- assinatura é do CASAL, mas fica no usuário que pagou; o plano vale para os dois enquanto o vínculo estiver ativo
CREATE TABLE IF NOT EXISTS assinaturas (usuario INTEGER PRIMARY KEY, plano TEXT NOT NULL, ativo_ate REAL NOT NULL, pedido TEXT);

-- perfil individual (privado)
CREATE TABLE IF NOT EXISTS perfis (usuario INTEGER PRIMARY KEY, nome TEXT NOT NULL DEFAULT '', nascimento TEXT NOT NULL DEFAULT '',
  fase TEXT NOT NULL DEFAULT '', objetivos TEXT NOT NULL DEFAULT '', limites TEXT NOT NULL DEFAULT '', afeto TEXT NOT NULL DEFAULT '',
  tom TEXT NOT NULL DEFAULT '', atualizado REAL NOT NULL);

-- o casal: convite por código; pausado/encerrado tira o núcleo da tela dos dois na hora
CREATE TABLE IF NOT EXISTS casais (id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, criado REAL NOT NULL,
  estado TEXT NOT NULL DEFAULT 'aguardando');   -- aguardando | ativo | pausado | encerrado
CREATE TABLE IF NOT EXISTS membros (casal INTEGER NOT NULL, usuario INTEGER NOT NULL UNIQUE, entrou REAL NOT NULL,
  PRIMARY KEY (casal, usuario));

-- conversa privada e memória privada
CREATE TABLE IF NOT EXISTS mensagens (id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, papel TEXT NOT NULL, texto TEXT NOT NULL, criado REAL NOT NULL);
CREATE INDEX IF NOT EXISTS mensagens_usuario ON mensagens(usuario, criado);
CREATE TABLE IF NOT EXISTS memorias (usuario INTEGER PRIMARY KEY, texto TEXT NOT NULL, atualizado REAL NOT NULL);

-- sinais privados por tema: vontade | interesse | curiosidade | talvez | sem_interesse | limite
CREATE TABLE IF NOT EXISTS sinais (usuario INTEGER NOT NULL, tema TEXT NOT NULL, estado TEXT NOT NULL, origem TEXT NOT NULL,
  atualizado REAL NOT NULL, PRIMARY KEY (usuario, tema));

-- o que o casal vê: afinidades reveladas e missões
CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY, casal INTEGER NOT NULL, tema TEXT NOT NULL, nivel TEXT NOT NULL,
  criado REAL NOT NULL, UNIQUE (casal, tema));
CREATE TABLE IF NOT EXISTS missoes (id INTEGER PRIMARY KEY, casal INTEGER NOT NULL, tema TEXT NOT NULL, tipo TEXT NOT NULL,
  titulo TEXT NOT NULL, texto TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'aberta', criado REAL NOT NULL, concluida REAL);
CREATE TABLE IF NOT EXISTS checkins (id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, casal INTEGER, conexao INTEGER NOT NULL,
  prioridade TEXT NOT NULL DEFAULT '', criado REAL NOT NULL);
"""


class BancoSQLite:
    def __init__(self, caminho: str):
        self._trava = threading.RLock()
        self.con = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)

    @contextmanager
    def tx(self):
        with self._trava:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                yield self.con
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise

    def exec(self, sql: str, args: tuple = ()):
        with self._trava:
            return self.con.execute(sql, args)

    def um(self, sql: str, args: tuple = ()) -> dict | None:
        with self._trava:
            r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def todos(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._trava:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]


def agora() -> float:
    return time.time()


def Banco(caminho: str):
    """Postgres central (banco `produtos`, schema do produto) quando PRODUTOS_DATABASE_URL existe; senão o SQLite de antes
    (plano de volta). Spec 57, seção 8. PRODUTOS_SCHEMA_TESTE=1 dá um schema novo por instância (testes isolados)."""
    dsn = os.environ.get("PRODUTOS_DATABASE_URL")
    if not dsn:
        return BancoSQLite(caminho)
    from produtos_core.banco_pg import Banco as BancoPG
    schema = os.environ.get("PRODUTOS_SCHEMA", "boateazul")
    if os.environ.get("PRODUTOS_SCHEMA_TESTE"):
        schema = "teste_" + uuid.uuid4().hex[:10]
    return BancoPG(dsn, schema, ESQUEMA)
