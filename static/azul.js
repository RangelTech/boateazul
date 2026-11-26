// VolupIA: cortina que abre, balões que se fundem no scroll, quiz do mapa inicial, contador e convite.
;(() => {
  const $ = (q, r = document) => r.querySelector(q)
  const $$ = (q, r = document) => [...r.querySelectorAll(q)]
  const reduzir = matchMedia('(prefers-reduced-motion: reduce)').matches

  // convite pelo link: guarda o código para usar depois do login (o app lê e entra no casal)
  const conv = new URLSearchParams(location.search).get('convite')
  if (conv) { try { localStorage.setItem('ba_convite', conv.toUpperCase()) } catch {} }

  // cortina abre logo depois de carregar
  const heroi = $('#heroi')
  if (heroi) setTimeout(() => heroi.classList.add('aberta'), reduzir ? 0 : 450)

  // tese: os dois balões vêm das laterais e se fundem; aparece a frase
  const tese = $('#tese')
  if (tese) {
    const a = $('.bal.a', tese), b = $('.bal.b', tese), u = $('.uniao', tese)
    const passo = () => {
      const r = tese.getBoundingClientRect()
      const total = r.height - innerHeight
      const p = Math.min(1, Math.max(0, -r.top / Math.max(1, total)))
      const larg = Math.min(innerWidth, 1200)
      const ida = Math.min(1, p / 0.6)
      const x = (1 - ida) * larg * 0.28
      const y = (1 - ida) * 60
      const funde = Math.max(0, (p - 0.55) / 0.3)
      a.style.transform = `translate(${-x - 40}px, ${-y - 70}px) scale(${1 - funde * 0.25})`
      b.style.transform = `translate(${x + 40}px, ${y + 70}px) scale(${1 - funde * 0.25})`
      a.style.opacity = b.style.opacity = String(1 - Math.min(1, funde * 1.2))
      u.style.opacity = String(Math.min(1, funde * 1.4))
      u.style.transform = `scale(${0.92 + Math.min(1, funde) * 0.08})`
    }
    addEventListener('scroll', passo, { passive: true }); addEventListener('resize', passo); passo()
  }

  // quiz do mapa inicial
  const caixa = $('#quiz-caixa')
  if (caixa) {
    const resp = []
    const barra = $('.barra i', caixa)
    const ir = (n) => { $$('.q', caixa).forEach((q) => q.classList.toggle('on', +q.dataset.q === n)); barra.style.width = (n / 3 * 100) + '%' }
    const PERFIS = {
      conversa: ['Cúmplices de alma', 'Vocês querem se reencontrar nas palavras. A VolupIA vai abrir conversas que vocês adiam há tempos, no tempo de cada um.', ['Conversas profundas', 'Planos a dois', 'Carinho no dia a dia']],
      novidade: ['Aventureiros em pausa', 'A rotina engoliu as surpresas. A VolupIA vai descobrir que tipo de novidade empolga vocês dois e entregar missões prontas.', ['Escapadas surpresa', 'Encontros novos', 'Primeiras vezes']],
      desejo: ['Fogo guardado', 'O desejo está aí, só falta coragem de falar. Cada um conta em segredo; o que for dos dois aparece na hora certa.', ['Intimidade sem pressa', 'Fantasias leves', 'Noites especiais']],
    }
    caixa.addEventListener('click', (e) => {
      const bt = e.target.closest('button[data-v]')
      if (!bt) return
      resp.push(bt.dataset.v)
      const n = resp.length
      if (n < 3) return ir(n)
      const p = PERFIS[resp[1]] || PERFIS.conversa
      const extra = { romance: 'Jantar à luz de velas', aventura: 'Surpresa fora de casa', ousado: 'Uma noite ousada' }[resp[2]]
      $('#res-tit').textContent = 'Vocês são: ' + p[0]
      $('#res-txt').textContent = p[1]
      $('#res-tags').innerHTML = [...p[2], extra].map((t) => `<span>${t}</span>`).join('')
      ir(3)
    })
  }

  // contador que sobe quando aparece
  const cont = $('[data-conta-ate]')
  if (cont) {
    const alvo = +cont.dataset.contaAte
    const io = new IntersectionObserver((es) => {
      if (!es[0].isIntersecting) return
      io.disconnect()
      const t0 = performance.now(), dur = reduzir ? 0 : 1800
      const tique = (t) => {
        const p = dur ? Math.min(1, (t - t0) / dur) : 1
        cont.textContent = Math.round(alvo * (1 - Math.pow(1 - p, 3))).toLocaleString('pt-BR')
        if (p < 1) requestAnimationFrame(tique)
      }
      requestAnimationFrame(tique)
    }, { threshold: 0.4 })
    io.observe(cont)
  }
})()
