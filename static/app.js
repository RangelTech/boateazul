// App da VolupIA: conversa privada, cartões de afinidade, Núcleo do casal, missões e vínculo.
;(() => {
  const $ = (q, r = document) => r.querySelector(q)
  const $$ = (q, r = document) => [...r.querySelectorAll(q)]
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  let conta = null
  let toastT = 0
  const toast = (t) => { const el = $('#toast'); el.textContent = t; el.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (el.hidden = true), 4200) }
  async function api(metodo, url, corpo) {
    const r = await fetch(url, { method: metodo, headers: corpo ? { 'Content-Type': 'application/json' } : {}, body: corpo ? JSON.stringify(corpo) : undefined })
    let j = {}
    try { j = await r.json() } catch {}
    if (r.status === 401) { location.href = '/?entrar=1'; throw new Error('login') }
    if (!r.ok) throw Object.assign(new Error(typeof j.detail === 'string' ? j.detail : 'Não deu certo. Tente de novo.'), { status: r.status })
    return j
  }

  // ---------- abas ----------
  function irAba(nome) {
    $$('.abas button').forEach((b) => b.classList.toggle('on', b.dataset.aba === nome))
    $$('.aba').forEach((s) => s.classList.toggle('on', s.id === 'aba-' + nome))
    history.replaceState(null, '', '#' + nome)
    ;({ conversa: carregarChat, afinidades: carregarTemas, nucleo: carregarNucleo, missoes: carregarMissoes, vinculo: carregarVinculo })[nome]?.()
  }
  $$('.abas button').forEach((b) => (b.onclick = () => irAba(b.dataset.aba)))
  // link com #aba (ou voltar do celular) troca de aba sem recarregar
  addEventListener('hashchange', () => { const n = location.hash.slice(1); if (n && $('#aba-' + n) && !$('#aba-' + n).classList.contains('on')) irAba(n) })

  // ---------- conversa ----------
  const SUGESTOES = ['Sinto que caímos na rotina', 'Quero surpreender meu parceiro(a)', 'Tenho vontade de algo novo, mas tenho vergonha de falar', 'Como reacender o desejo?']
  function bolha(papel, texto) {
    const d = document.createElement('div')
    d.className = 'm ' + (papel === 'usuario' ? 'eu' : 'ia')
    d.textContent = texto
    $('#chat').appendChild(d)
    $('.palco').scrollTop = $('.palco').scrollHeight
    return d
  }
  async function carregarChat() {
    const j = await api('GET', '/api/conversa')
    const c = $('#chat')
    c.innerHTML = ''
    if (!j.mensagens.length) {
      c.innerHTML = `<div class="vazio"><b>Aqui ninguém escuta além da sua IA.</b><br>Conte como está a relação, o que falta, o que você deseja. Comece por aqui:
        <div class="sugestoes">${SUGESTOES.map((s) => `<button type="button">${esc(s)}</button>`).join('')}</div></div>`
      $$('.sugestoes button', c).forEach((b) => (b.onclick = () => { $('#txt').value = b.textContent; enviar() }))
    }
    j.mensagens.forEach((m) => bolha(m.papel, m.texto))
  }
  async function enviar(e) {
    e && e.preventDefault()
    const t = $('#txt').value.trim()
    if (!t) return
    $('#txt').value = ''
    $('.vazio', $('#chat'))?.remove()
    bolha('usuario', t)
    const d = bolha('ia', 'Digitando…')
    d.classList.add('digitando')
    try {
      const j = await api('POST', '/api/conversa', { texto: t })
      d.classList.remove('digitando')
      d.textContent = j.resposta
      setTimeout(atualizarBolhaNucleo, 4000) // a IA marca os sinais em segundo plano; se deu match, o Núcleo avisa
    } catch (err) {
      d.classList.remove('digitando')
      d.textContent = err.message
      if (err.status === 403) irAba('vinculo')
    }
  }
  $('#compor').onsubmit = enviar
  $('#txt').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar() } })
  $('#txt').addEventListener('input', (e) => { e.target.style.height = 'auto'; e.target.style.height = Math.min(160, e.target.scrollHeight) + 'px' })

  // ---------- afinidades ----------
  async function carregarTemas() {
    const j = await api('GET', '/api/temas')
    const est = j.estados
    $('#cats').innerHTML = j.categorias.map((c) => `<div class="cat"><h2>${esc(c.nome)}${c.id === 'fantasias' && conta?.plano !== 'intimo' ? '<span class="trava">PLANO ÍNTIMO</span>' : ''}</h2>
      <div class="cartoes">${c.temas.map((t) => `<div class="cartao" data-tema="${t.id}"><h4>${esc(t.titulo)}</h4><div class="estados">
      ${Object.entries(est).map(([k, v]) => `<button type="button" data-e="${k}" class="${t.meu === k ? 'on' : ''}">${esc(v)}</button>`).join('')}</div></div>`).join('')}</div></div>`).join('')
    $$('.cartao').forEach((ca) => ca.addEventListener('click', async (e) => {
      const b = e.target.closest('button[data-e]')
      if (!b) return
      try {
        const r = await api('POST', '/api/sinal', { tema: ca.dataset.tema, estado: b.dataset.e })
        $$('button', ca).forEach((x) => x.classList.toggle('on', x === b))
        if (r.revelados) { toast('✨ Uma afinidade nova apareceu no Núcleo do casal!'); atualizarBolhaNucleo() } else toast('Guardado em segredo.')
      } catch (err) { toast(err.message); if (err.status === 403) irAba('vinculo') }
    }))
  }

  // ---------- núcleo ----------
  let vistos = +(localStorage.getItem('ba_vistos') || 0)
  async function atualizarBolhaNucleo() {
    try {
      const j = await api('GET', '/api/nucleo')
      const n = j.matches.length - vistos
      $('#b-nucleo').hidden = n <= 0
      $('#b-nucleo').textContent = n
    } catch {}
  }
  async function carregarNucleo() {
    const j = await api('GET', '/api/nucleo')
    const el = $('#nucleo')
    vistos = j.matches.length
    try { localStorage.setItem('ba_vistos', vistos) } catch {}
    $('#b-nucleo').hidden = true
    if (j.estado !== 'ativo') {
      const msg = { sem_vinculo: 'Convide quem você ama para abrir o Núcleo do casal.', aguardando: 'O convite foi enviado. Assim que a outra pessoa entrar, o Núcleo se abre.', pausado: 'O vínculo está pausado. Retome em "Perfil e vínculo" quando quiserem.' }[j.estado]
      el.innerHTML = `<div class="vazio">${esc(msg)}<div class="linha" style="justify-content:center"><button class="btn btn-pri" data-ir="vinculo">Ir para o vínculo</button></div></div>`
      $('[data-ir]', el).onclick = () => irAba('vinculo')
      return
    }
    $('#nucleo-sub').textContent = `Você e ${j.parceiro || 'quem você ama'}: o que vocês dois querem, sem saber quem falou primeiro.`
    if (!j.matches.length) {
      el.innerHTML = '<div class="vazio"><b>Ainda nenhuma descoberta.</b><br>Converse com a sua IA e marque as afinidades. Quando os dois quiserem a mesma coisa, ela aparece aqui.</div>'
      return
    }
    el.innerHTML = `<div class="descobertas">${j.matches.map((m, i) => `<div class="desc" style="animation-delay:${i * 90}ms"><small>${esc(m.nivel)} · ${esc(m.categoria)}</small><h3>${esc(m.titulo)}</h3><p>${esc(m.frase)}.</p></div>`).join('')}</div>`
  }

  // ---------- missões ----------
  async function carregarMissoes() {
    const j = await api('GET', '/api/nucleo')
    const el = $('#missoes')
    if (!j.missoes.length) { el.innerHTML = '<div class="vazio">As missões aparecem quando surgir a primeira afinidade de vocês.</div>'; return }
    const tipo = { conversa: 'Conversa', encontro: 'Encontro', experiencia: 'Experiência' }
    el.innerHTML = j.missoes.map((m) => `<div class="mis ${m.estado === 'concluida' ? 'feita' : ''}"><span>${tipo[m.tipo] || m.tipo}</span><h3>${esc(m.titulo)}</h3><p>${esc(m.texto)}</p>
      ${m.estado === 'concluida' ? '<b class="mut">✓ Feita</b>' : `<button class="btn btn-sec" data-mid="${m.id}">Marcar como feita</button>`}</div>`).join('')
    $$('[data-mid]', el).forEach((b) => (b.onclick = async () => { await api('POST', `/api/missao/${b.dataset.mid}/concluir`); toast('Missão cumprida. ♥'); carregarMissoes() }))
  }
  $$('#notas button').forEach((b) => (b.onclick = async () => {
    try {
      const j = await api('POST', '/api/checkin', { conexao: +b.dataset.n })
      $('#checkin-msg').textContent = j.media_casal ? `Média do casal nesta semana: ${j.media_casal} de 5.` : 'Guardado. A média aparece quando os dois responderem.'
    } catch (err) { toast(err.message) }
  }))

  // ---------- perfil e vínculo ----------
  async function carregarConta() {
    conta = await api('GET', '/api/conta')
    $('#quem').textContent = conta.perfil.nome || conta.email
    const f = $('#perfil')
    Object.entries(conta.perfil).forEach(([k, v]) => { if (f.elements[k]) f.elements[k].value = v || '' })
    return conta
  }
  async function carregarVinculo() {
    await carregarConta()
    carregarWhats()
    const el = $('#vinculo')
    const c = conta.casal
    if (!c) {
      el.innerHTML = `<h3>Convidar quem você ama</h3><p class="mut">Gere um convite e mande o link. Cada um tem a própria conta e a própria conversa privada.</p>
        <div class="linha"><button class="btn btn-pri" id="criar">Gerar convite</button></div>
        <h3 style="margin-top:22px">Recebeu um convite?</h3><div class="linha"><input id="cod" placeholder="Código do convite" maxlength="8" style="flex:1"><button class="btn btn-sec" id="usar">Entrar no casal</button></div>`
      $('#criar').onclick = async () => { try { await api('POST', '/api/casal/criar'); carregarVinculo() } catch (err) { toast(err.message) } }
      $('#usar').onclick = () => usarConvite($('#cod').value)
      return
    }
    if (c.estado === 'aguardando') {
      const link = `${location.origin}/?convite=${c.codigo}`
      el.innerHTML = `<h3>Convite pronto</h3><p class="mut">Mande este link (ou o código) para quem você ama. Quando entrar, o Núcleo do casal se abre.</p>
        <div class="codigo">${esc(c.codigo)}</div><div class="linha"><button class="btn btn-pri" id="copiar">Copiar link do convite</button>
        <a class="btn btn-sec" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent('Vem comigo para a VolupIA? ' + link)}">Mandar no WhatsApp</a></div>
        <div class="linha"><button class="link" id="cancelar">Cancelar convite</button></div>`
      $('#copiar').onclick = async () => { try { await navigator.clipboard.writeText(link); toast('Link copiado.') } catch { toast(link) } }
      $('#cancelar').onclick = async () => { await api('POST', '/api/casal/desvincular'); carregarVinculo() }
      return
    }
    el.innerHTML = `<h3>Vínculo ${c.estado === 'ativo' ? 'ativo' : 'pausado'} ${c.estado === 'ativo' ? '♥' : ''}</h3><p class="mut">Você está vinculado(a) a <b>${esc(c.parceiro || 'seu par')}</b>. ${c.estado === 'pausado' ? 'Enquanto estiver pausado, o Núcleo fica escondido para os dois.' : 'Pausar esconde o Núcleo para os dois na hora.'}</p>
      <div class="linha">${c.estado === 'ativo' ? '<button class="btn btn-sec" data-acao="pausar">Pausar vínculo</button>' : '<button class="btn btn-pri" data-acao="retomar">Retomar vínculo</button>'}
      <button class="btn btn-sec" data-acao="desvincular">Desvincular</button></div>`
    $$('[data-acao]', el).forEach((b) => (b.onclick = async () => {
      if (b.dataset.acao === 'desvincular' && !confirm('Desvincular encerra o Núcleo para os dois. As conversas privadas continuam de cada um. Continuar?')) return
      await api('POST', '/api/casal/' + b.dataset.acao)
      toast('Pronto.')
      carregarVinculo()
    }))
  }
  // ---------- WhatsApp (spec 59): cada um vincula o próprio número mandando um código do próprio aparelho ----------
  let esperaWhats = null
  async function carregarWhats() {
    const el = $('#whats')
    let w
    try { w = await api('GET', '/api/whats') } catch { el.hidden = true; return }
    el.hidden = false
    if (w.vinculado) {
      clearInterval(esperaWhats); esperaWhats = null
      el.innerHTML = `<h3>WhatsApp vinculado</h3><p class="mut">Número <b>${esc(w.numero)}</b>. Converse com a sua assistente pelo WhatsApp: é a mesma conversa privada daqui, só sua.</p>
        <label class="linha" style="gap:8px;align-items:center"><input type="checkbox" id="w-avisos" ${w.avisos ? 'checked' : ''} style="width:auto"> Avisar quando houver novidade no Núcleo (o aviso nunca diz o assunto)</label>
        <div class="linha"><button class="link" id="w-sair">Desvincular WhatsApp</button></div>`
      $('#w-avisos').onchange = async (e) => { await api('POST', '/api/whats/avisos', { ligado: e.target.checked }); toast('Pronto.') }
      $('#w-sair').onclick = async () => { if (!confirm('Desvincular o seu WhatsApp?')) return; await api('DELETE', '/api/whats'); carregarWhats() }
      return
    }
    if (!w.disponivel) {
      el.innerHTML = `<h3>WhatsApp</h3><p class="mut">Em breve você vai poder conversar com a sua assistente também pelo WhatsApp.</p>`
      return
    }
    el.innerHTML = `<h3>Vincular meu WhatsApp</h3><p class="mut">Converse com a sua assistente pelo WhatsApp. Cada um do casal vincula o próprio número; as conversas continuam separadas.</p>
      <div class="linha"><button class="btn btn-pri" id="w-vincular">Vincular meu WhatsApp</button></div><div id="w-passo"></div>`
    $('#w-vincular').onclick = async () => {
      try {
        const j = await api('POST', '/api/whats/codigo')
        $('#w-passo').innerHTML = `<p class="mut" style="margin-top:14px">Toque no botão e envie a mensagem que já vai escrita. O código vale ${j.vale_min} minutos.</p>
          <div class="codigo">${esc(j.codigo)}</div><div class="linha"><a class="btn btn-sec" id="w-link" target="_blank" rel="noopener" href="${esc(j.link)}">Abrir o WhatsApp e enviar</a></div>`
        clearInterval(esperaWhats)
        let voltas = 0
        esperaWhats = setInterval(async () => { if (++voltas > 120) return clearInterval(esperaWhats); const x = await api('GET', '/api/whats').catch(() => ({})); if (x.vinculado) { toast('WhatsApp vinculado!'); carregarWhats() } }, 5000)
      } catch (err) { toast(err.message) }
    }
  }
  async function usarConvite(cod) {
    try {
      const r = await api('POST', '/api/casal/entrar', { codigo: String(cod || '').trim() })
      try { localStorage.removeItem('ba_convite') } catch {}
      toast(r.revelados ? `Vínculo criado! ${r.revelados} afinidade(s) já apareceram.` : 'Vínculo criado! O Núcleo do casal está aberto.')
      carregarVinculo()
    } catch (err) { toast(err.message) }
  }
  $('#perfil').onsubmit = async (e) => {
    e.preventDefault()
    const dados = Object.fromEntries(new FormData(e.target).entries())
    try {
      await api('POST', '/api/perfil', dados)
      $('#perfil-msg').textContent = 'Perfil salvo.'
      await carregarConta()
      if (pendente()) usarConvite(pendente())
    } catch (err) { $('#perfil-msg').textContent = err.message }
  }
  const pendente = () => { try { return localStorage.getItem('ba_convite') } catch { return null } }
  $('#sair').onclick = async () => { await api('POST', '/api/sair'); location.href = '/' }

  // ---------- início ----------
  ;(async () => {
    await carregarConta()
    if (!conta.adulto) { irAba('vinculo'); toast('Complete o perfil (data de nascimento) para começar. A VolupIA é só para maiores de 18.'); return }
    if (pendente() && !conta.casal) { await usarConvite(pendente()) }
    irAba((location.hash || '#conversa').slice(1))
    atualizarBolhaNucleo()
  })()
})()
