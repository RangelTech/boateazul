"""Temas, estados e o motor de match bilateral da Boate Azul.

Regra que não quebra (spec 45 §G): revelar_match = elegivel(A, tema) AND elegivel(B, tema) AND vinculo_ativo.
O casal nunca vê quem trouxe o tema, quem marcou primeiro, nem o que não deu match.
"""
from __future__ import annotations

ESTADOS = {
    "vontade": "Tenho vontade",
    "interesse": "Tenho interesse",
    "curiosidade": "Tenho curiosidade",
    "talvez": "Talvez no futuro",
    "sem_interesse": "Não tenho interesse",
    "limite": "É um limite",
}
ELEGIVEIS = {"vontade", "interesse", "curiosidade"}
FORCA = {"vontade": 3, "interesse": 2, "curiosidade": 1}

CATEGORIAS = {
    "conversa": "Conversa e conexão",
    "rotina": "Sair da rotina",
    "carinho": "Carinho e afeto",
    "encontros": "Encontros e programas",
    "intimidade": "Intimidade",
    "fantasias": "Fantasias e jogos",
}

# tema -> (categoria, título, leve?, missões [(tipo, título, texto)])
TEMAS: dict[str, tuple] = {
    "conversa-profunda": ("conversa", "Conversas mais profundas", True, [("conversa", "36 perguntas a dois", "Escolham 6 perguntas profundas (sonhos, medos, memórias de infância) e respondam um de cada vez, sem celular, por 30 minutos.")]),
    "elogios": ("conversa", "Mais elogios no dia a dia", True, [("conversa", "Semana do elogio", "Cada um manda um elogio sincero por dia para o outro, durante 7 dias, em horários diferentes.")]),
    "desabafo": ("conversa", "Espaço para desabafar sem julgamento", True, [("conversa", "Dez minutos de escuta", "Um fala por 10 minutos sobre o dia sem ser interrompido; depois trocam. Quem escuta só pergunta \"o que mais?\".")]),
    "planos-futuro": ("conversa", "Sonhar juntos o futuro", True, [("conversa", "Mapa dos próximos 5 anos", "Desenhem juntos três sonhos para os próximos 5 anos: um de viagem, um de casa, um só de vocês dois.")]),
    "memorias": ("conversa", "Relembrar a história de vocês", True, [("encontro", "Volta ao primeiro encontro", "Refaçam o primeiro encontro (ou o mais marcante): mesmo lugar, mesma comida, mesma música.")]),
    "rotina-nova": ("rotina", "Quebrar a rotina da semana", True, [("encontro", "Noite sem tela", "Uma noite por semana sem celular e sem série: jogo de tabuleiro, cozinhar juntos ou caminhar.")]),
    "viagem-surpresa": ("rotina", "Viagem ou escapada surpresa", True, [("experiencia", "Escapada de 24 horas", "Um planeja em segredo uma escapada de 24 horas perto de casa; o outro só sabe a roupa que precisa levar.")]),
    "aventura": ("rotina", "Aventuras ao ar livre", True, [("experiencia", "Primeira vez juntos", "Escolham algo que nenhum dos dois fez: trilha, aula de dança, escalada, passeio de balão.")]),
    "cozinhar-juntos": ("rotina", "Cozinhar juntos", True, [("encontro", "Jantar a quatro mãos", "Escolham uma receita nova e difícil, cozinhem juntos com vinho e música, e jantem à luz de velas.")]),
    "hobby-a-dois": ("rotina", "Um hobby só de vocês", True, [("experiencia", "Aula experimental a dois", "Façam uma aula experimental juntos (dança de salão, cerâmica, fotografia) e decidam se continuam.")]),
    "toque": ("carinho", "Mais toque e carinho no dia a dia", True, [("experiencia", "Abraço de 20 segundos", "Todo dia, um abraço de 20 segundos ao chegar em casa. Sem pressa, sem falar nada.")]),
    "massagem": ("carinho", "Massagem relaxante", True, [("experiencia", "Noite de massagem", "Óleo morno, luz baixa, 20 minutos para cada um. Quem recebe só diz \"mais\" ou \"menos\".")]),
    "cartas": ("carinho", "Bilhetes e cartas de amor", True, [("conversa", "Carta escondida", "Cada um escreve uma carta à mão e esconde num lugar que o outro vai achar durante a semana.")]),
    "cuidado": ("carinho", "Sentir-se mais cuidado(a)", True, [("conversa", "Manual do meu carinho", "Cada um lista 3 coisas pequenas que fazem se sentir amado(a). Trocam as listas e fazem uma por dia.")]),
    "presentes": ("carinho", "Pequenos presentes e surpresas", True, [("experiencia", "Surpresa de 30 reais", "Cada um faz uma surpresa de até 30 reais para o outro nesta semana. Vale mais a ideia que o preço.")]),
    "date-night": ("encontros", "Encontro romântico fixo", True, [("encontro", "Date night da semana", "Marquem na agenda um encontro por semana, com roupa de sair, mesmo que seja em casa.")]),
    "jantar-fora": ("encontros", "Jantares especiais fora", True, [("encontro", "Restaurante novo", "Escolham um restaurante que nunca foram, com reserva e roupa especial.")]),
    "dancar": ("encontros", "Sair para dançar", True, [("encontro", "Noite de dança", "Saiam para dançar: samba, forró, balada ou na sala de casa com a playlist de vocês.")]),
    "hotel": ("encontros", "Noite em hotel", False, [("experiencia", "Noite fora de casa", "Reservem uma noite em hotel ou pousada só para vocês, sem filhos e sem trabalho.")]),
    "piquenique": ("encontros", "Piquenique ou pôr do sol", True, [("encontro", "Pôr do sol a dois", "Levem uma toalha, frutas e algo para brindar e assistam ao pôr do sol juntos.")]),
    "iniciativa": ("intimidade", "Mais iniciativa na intimidade", False, [("conversa", "Quem começa hoje", "Combinem dias em que cada um toma a iniciativa, sem cobrança: a ideia é sentir-se desejado(a).")]),
    "preliminares": ("intimidade", "Preliminares mais longas", False, [("experiencia", "Sem pressa", "Uma noite em que a regra é não ter pressa: 30 minutos de beijos e carinho antes de qualquer outra coisa.")]),
    "novos-lugares": ("intimidade", "Intimidade em lugares novos da casa", False, [("experiencia", "Fora do quarto", "Escolham juntos um cômodo da casa que nunca foi palco de vocês e preparem o clima.")]),
    "lingerie": ("intimidade", "Lingerie e roupas sensuais", False, [("experiencia", "Presente sensual", "Cada um escolhe uma peça para o outro usar numa noite combinada.")]),
    "conversa-desejos": ("intimidade", "Falar abertamente sobre desejos", False, [("conversa", "Sim, não, talvez", "Cada um preenche em segredo uma lista de sim/não/talvez e conversam só sobre os \"sim\" em comum.")]),
    "frequencia": ("intimidade", "Mais momentos íntimos", False, [("conversa", "Nosso ritmo", "Conversem sem cobrança sobre o ritmo que faria os dois se sentirem bem, e combinem um teste de 2 semanas.")]),
    "banho-a-dois": ("intimidade", "Banho a dois", False, [("experiencia", "Banho de espuma", "Velas, banho demorado e música. Sem celular por perto.")]),
    "brinquedos": ("intimidade", "Brinquedos para casais", False, [("experiencia", "Primeiro brinquedo", "Escolham juntos, num site discreto, um brinquedo para casais para estrear numa noite combinada.")]),
    "manha": ("intimidade", "Intimidade de manhã", False, [("experiencia", "Bom dia diferente", "Coloquem o despertador 30 minutos mais cedo num dia de folga.")]),
    "fotos-sensuais": ("intimidade", "Fotos sensuais só para o casal", False, [("experiencia", "Ensaio a dois", "Um ensaio de fotos sensuais feito por vocês, guardado só no celular dos dois (ou apagado depois).")]),
    "roleplay": ("fantasias", "Interpretar personagens", False, [("experiencia", "Encontro de desconhecidos", "Marquem um encontro num bar fingindo que não se conhecem. Cada um cria um personagem.")]),
    "jogos-picantes": ("fantasias", "Jogos picantes de casal", False, [("experiencia", "Dado do desejo", "Joguem um jogo de cartas ou dados picantes; cada um pode vetar 2 cartas sem explicar.")]),
    "vendas": ("fantasias", "Vendas nos olhos e sentidos", False, [("experiencia", "Noite dos sentidos", "Um fica de olhos vendados e o outro explora os sentidos: sabores, texturas, temperaturas.")]),
    "dominacao-leve": ("fantasias", "Quem manda hoje (leve)", False, [("experiencia", "Hoje eu conduzo", "Um conduz a noite inteira, com uma palavra de segurança combinada. Na próxima, invertem.")]),
    "striptease": ("fantasias", "Dança sensual / striptease", False, [("experiencia", "Show particular", "Um prepara uma dança sensual para o outro, com a música escolhida por quem vai assistir.")]),
    "lugares-ousados": ("fantasias", "Lugares mais ousados", False, [("experiencia", "Fora do comum", "Escolham juntos um lugar diferente e seguro (carro, varanda, hotel temático) para uma noite especial.")]),
    "fantasia-filme": ("fantasias", "Recriar uma cena de filme", False, [("experiencia", "Cena de cinema", "Escolham juntos uma cena romântica ou sensual de filme e recriem do jeito de vocês.")]),
    "mensagens-picantes": ("fantasias", "Mensagens picantes durante o dia", False, [("conversa", "Provocação do dia", "Durante um dia de trabalho, troquem mensagens que vão esquentando até a noite.")]),
    "motel": ("fantasias", "Ir a um motel temático", False, [("experiencia", "Suíte temática", "Escolham juntos uma suíte temática e reservem uma noite.")]),
    "sexting-audio": ("fantasias", "Áudios sensuais", False, [("conversa", "Voz no ouvido", "Mandem um áudio sensual um para o outro; ouçam só quando estiverem sozinhos.")]),
}

NIVEIS = {
    "afinidade": "Afinidade descoberta",
    "conversar": "Afinidade para conversar",
    "experiencia": "Experiência em comum",
    "objetivo": "Objetivo compartilhado",
}


def elegivel(estado: str | None) -> bool:
    return estado in ELEGIVEIS


def nivel_de(ea: str, eb: str, tema: str) -> str:
    cat = TEMAS[tema][0]
    if cat == "conversa":
        return "objetivo" if min(FORCA[ea], FORCA[eb]) >= 2 else "afinidade"
    if min(FORCA[ea], FORCA[eb]) >= 3:
        return "experiencia"
    if min(FORCA[ea], FORCA[eb]) >= 2:
        return "conversar"
    return "afinidade"


def revelar(db, casal: dict) -> list[str]:
    """Recalcula o casal e publica os matches novos (com uma missão cada). Devolve os temas revelados agora."""
    from app.db import agora
    if not casal or casal["estado"] != "ativo":
        return []
    ms = [m["usuario"] for m in db.todos("SELECT usuario FROM membros WHERE casal=?", (casal["id"],))]
    if len(ms) != 2:
        return []
    a, b = ms
    sa = {s["tema"]: s["estado"] for s in db.todos("SELECT tema, estado FROM sinais WHERE usuario=?", (a,))}
    sb = {s["tema"]: s["estado"] for s in db.todos("SELECT tema, estado FROM sinais WHERE usuario=?", (b,))}
    novos = []
    for tema in sorted(set(sa) & set(sb)):
        if tema not in TEMAS or not (elegivel(sa[tema]) and elegivel(sb[tema])):
            continue
        if db.um("SELECT 1 FROM matches WHERE casal=? AND tema=?", (casal["id"], tema)):
            continue
        db.exec("INSERT INTO matches(casal,tema,nivel,criado) VALUES(?,?,?,?)", (casal["id"], tema, nivel_de(sa[tema], sb[tema], tema), agora()))
        tipo, titulo, texto = TEMAS[tema][3][0]
        db.exec("INSERT INTO missoes(casal,tema,tipo,titulo,texto,criado) VALUES(?,?,?,?,?,?)", (casal["id"], tema, tipo, titulo, texto, agora()))
        novos.append(tema)
    return novos


def temas_para_explorar(db, usuario: int, casal: dict | None, limite: int = 3) -> list[str]:
    """Temas que a IA desta pessoa pode puxar de forma natural: o(a) parceiro(a) marcou elegível e esta pessoa ainda não
    respondeu. Devolve SÓ títulos de tema (sem texto, sem origem, sem dizer que alguém marcou)."""
    if not casal or casal["estado"] != "ativo":
        return []
    outro = db.um("SELECT usuario FROM membros WHERE casal=? AND usuario<>?", (casal["id"], usuario))
    if not outro:
        return []
    meus = {s["tema"] for s in db.todos("SELECT tema FROM sinais WHERE usuario=?", (usuario,))}
    dele = [s["tema"] for s in db.todos("SELECT tema FROM sinais WHERE usuario=? AND estado IN ('vontade','interesse','curiosidade') ORDER BY atualizado", (outro["usuario"],))]
    # mistura com temas leves que ninguém marcou, para a pergunta nunca "entregar" a origem
    leves = [t for t, v in TEMAS.items() if v[2] and t not in meus]
    cand = [t for t in dele if t not in meus and t in TEMAS]
    out = []
    for i, t in enumerate(cand[:limite]):
        out.append(TEMAS[t][1])
        if i < len(leves):
            out.append(TEMAS[leves[(usuario * 7 + i) % len(leves)]][1])
    return out[: limite * 2]
