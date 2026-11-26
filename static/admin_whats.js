// Aba "WhatsApp" do /admin da Boate Azul (spec 59): liga o número da casa no gateway de canais (QR) e mostra o estado.
// NUNCA ler este QR com o número pessoal do Lucas: só com o chip da Boate Azul.
;(() => {
  const $ = (s, r = document) => r.querySelector(s)
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  const api = async (url, opt = {}) => {
    const r = await fetch(url, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, ...opt })
    let j = {}; try { j = await r.json() } catch {}
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Não deu certo (' + r.status + ')')
    return j
  }
  const nav = $('nav.abas'), main = $('main')
  if (!nav || !main) return
  const ESTADOS = { desligado: 'não conectado', pending_auth: 'esperando ler o QR', connected: 'conectado', disconnected: 'desconectado', reauth_required: 'precisa reconectar', degraded: 'instável' }
  nav.insertAdjacentHTML('beforeend', '<button data-aba="whats" aria-selected="false">WhatsApp</button>')
  main.insertAdjacentHTML('beforeend', `<section data-p="whats" hidden><div class="painel" id="w-casa" style="max-width:560px;padding:20px"></div></section>`)
  let espera = null
  function qr(dado) { const q = qrcode(0, 'M'); q.addData(dado); q.make(); return q.createSvgTag({ cellSize: 5, margin: 2, scalable: false }) }
  function desenhar(v) {
    const el = $('#w-casa')
    const ok = v.estado === 'connected'
    el.innerHTML = `<h3 style="margin:0 0 6px">Número da Boate Azul</h3>
      <p class="msg">Estado: <b>${esc(ESTADOS[v.estado] || v.estado)}</b>${v.numero ? ' · ' + esc(v.numero) : ''} · ${v.vinculados} pessoa(s) com WhatsApp vinculado</p>
      ${v.qr ? `<p class="msg">Abra o WhatsApp do <b>chip da Boate Azul</b> (nunca o número pessoal), Aparelhos conectados, Conectar aparelho, e leia:</p><div style="background:#fff;display:inline-block;padding:8px;border-radius:12px">${qr(v.qr)}</div>` : ''}
      <div style="display:flex;gap:8px;margin-top:14px">${ok ? '<button class="btn" id="w-off">Desconectar</button>' : '<button class="btn pri" id="w-on">' + (v.estado === 'desligado' ? 'Conectar WhatsApp da casa' : 'Gerar QR de novo') + '</button>'}</div>
      <div class="msg" id="w-msg" role="status"></div>`
    const on = $('#w-on'), off = $('#w-off')
    if (on) on.onclick = async () => { try { desenhar(await api('/api/painel/whats/conectar', { method: 'POST' })); vigiar() } catch (err) { $('#w-msg').textContent = err.message } }
    if (off) off.onclick = async () => { if (!confirm('Desconectar o WhatsApp da Boate Azul? Ninguém conversa por lá até reconectar.')) return; desenhar(await api('/api/painel/whats/desconectar', { method: 'POST' })) }
  }
  function vigiar() {
    clearInterval(espera)
    let n = 0
    espera = setInterval(async () => {
      if (++n > 60 || $('[data-p="whats"]').hidden) return clearInterval(espera)
      try { const v = await api('/api/painel/whats'); if (v.estado === 'connected') { clearInterval(espera); desenhar(v) } } catch {}
    }, 4000)
  }
  nav.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-aba="whats"]'); if (!b) return
    document.querySelectorAll('[data-aba]').forEach((x) => x.setAttribute('aria-selected', String(x === b)))
    document.querySelectorAll('[data-p]').forEach((p) => (p.hidden = p.dataset.p !== 'whats'))
    $('#w-casa').innerHTML = '<p class="msg">Carregando…</p>'
    try { desenhar(await api('/api/painel/whats')) } catch (err) { $('#w-casa').innerHTML = '<p class="msg erro">' + esc(err.message) + '</p>' }
  })
})()
