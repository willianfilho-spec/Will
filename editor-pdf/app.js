// Folha Clara — editor e extrator de PDF que roda só no navegador.
// Renderização e extração: pdf.js (Apache-2.0). Gravação: pdf-lib (MIT).
import * as pdfjs from './vendor/pdfjs/pdf.min.mjs';
import { gerarPdfAnotado, gerarPdfComPaginas } from './exportar.js';
import { textoDaPagina, imagensDaPagina, paginaComoPng } from './extrair.js';
import { salvarSessao, lerSessao, apagarSessao } from './sessao.js';

pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/pdf.worker.min.mjs', import.meta.url).href;
const OPCOES_PDFJS = {
  standardFontDataUrl: new URL('./vendor/pdfjs/standard_fonts/', import.meta.url).href,
  cMapUrl: new URL('./vendor/pdfjs/cmaps/', import.meta.url).href,
  cMapPacked: true,
  verbosity: 0,
};

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const NS = 'http://www.w3.org/2000/svg';

const estado = {
  nome: '', bytes: null, doc: null,
  paginas: [],          // { w, h, transform, el, svg, canvas }
  anotacoes: [],
  ferramenta: 'selecionar',
  selecionada: null,
  historico: [],
  selecaoExtrair: new Set(),
};

// ---------- Avisos ----------
let tAviso;
function avisar(msg, erro = false) {
  const a = $('#aviso');
  a.textContent = msg; a.classList.toggle('erro', erro); a.hidden = false;
  clearTimeout(tAviso); tAviso = setTimeout(() => { a.hidden = true; }, erro ? 6000 : 3000);
}
function carregando(on) { $('#carregando').hidden = !on; }
const nomeBase = () => estado.nome.replace(/\.pdf$/i, '') || 'documento';
function baixar(blob, nome) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: nome });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

// ---------- Abrir PDF ----------
async function abrirArquivo(arq) {
  if (!arq) return;
  if (!/pdf$/i.test(arq.type) && !/\.pdf$/i.test(arq.name)) { avisar('Escolha um arquivo .pdf', true); return; }
  const bytes = new Uint8Array(await arq.arrayBuffer());
  if (await carregarDocumento(arq.name, bytes, [])) { salvarAgora(); avisar('Documento aberto. Nada foi enviado para fora deste navegador.'); }
}

async function carregarDocumento(nome, bytes, anotacoes) {
  carregando(true);
  try {
    // pdf.js transfere o buffer para o worker; guardamos uma cópia para a gravação.
    const tarefa = pdfjs.getDocument({ data: bytes.slice(), ...OPCOES_PDFJS });
    const doc = await tarefa.promise;
    estado.tarefa?.destroy(); // no pdf.js 6, destroy() fica na tarefa de carregamento
    Object.assign(estado, { nome, bytes, doc, tarefa, anotacoes, selecionada: null, historico: [], paginas: [] });
    estado.selecaoExtrair = new Set(Array.from({ length: doc.numPages }, (_, i) => i));
    $('#telaInicial').hidden = true;
    $('#abaEditar').disabled = $('#abaExtrair').disabled = false;
    $('#bFechar').hidden = false;
    $('#nomeDoc').textContent = nome;
    $('#contaPaginas').textContent = `${doc.numPages} página${doc.numPages > 1 ? 's' : ''}`;
    await montarPaginas();
    montarMiniaturas();
    $('#saidaTexto').hidden = true;
    $('#galeriaImagens').replaceChildren(); $('#resumoImagens').textContent = '';
    mudarModo('editar');
    atualizarContagem();
    return true;
  } catch (e) {
    console.warn('Falha ao abrir PDF:', e);
    avisar(e?.name === 'PasswordException' ? 'PDF protegido por senha: não suportado.' : 'Não foi possível ler este PDF.', true);
  } finally { carregando(false); }
}

function fechar() {
  estado.tarefa?.destroy();
  Object.assign(estado, { nome: '', bytes: null, doc: null, tarefa: null, paginas: [], anotacoes: [], selecionada: null, historico: [] });
  $('#paginas').replaceChildren(); $('#miniaturas').replaceChildren();
  $('#modoEditar').hidden = $('#modoExtrair').hidden = true;
  $('#telaInicial').hidden = false; $('#bFechar').hidden = true;
  $('#abaEditar').disabled = $('#abaExtrair').disabled = true;
  apagarSessao();
}

// ---------- Páginas ----------
async function montarPaginas() {
  const cont = $('#paginas');
  cont.replaceChildren();
  for (let i = 0; i < estado.doc.numPages; i++) {
    const pg = await estado.doc.getPage(i + 1);
    const vp = pg.getViewport({ scale: 1 });
    const el = document.createElement('div');
    el.className = 'pagina'; el.id = `pagina-${i + 1}`; el.dataset.idx = i;
    el.style.aspectRatio = `${vp.width} / ${vp.height}`;
    const canvas = document.createElement('canvas');
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'sobreposicao');
    svg.setAttribute('viewBox', `0 0 ${vp.width} ${vp.height}`);
    svg.dataset.ferr = estado.ferramenta;
    const rot = Object.assign(document.createElement('span'), { className: 'rotulo', textContent: `${i + 1}` });
    el.append(canvas, svg, rot);
    cont.append(el);
    estado.paginas.push({ w: vp.width, h: vp.height, transform: vp.transform, el, svg, canvas });
    ligarEventosPagina(i);
  }
  for (let i = 0; i < estado.paginas.length; i++) await renderizarPagina(i);
  desenharAnotacoes();
}

async function renderizarPagina(i) {
  const p = estado.paginas[i];
  const pg = await estado.doc.getPage(i + 1);
  const largura = Math.min(860, p.el.clientWidth || 860);
  const escala = (largura / p.w) * Math.min(window.devicePixelRatio || 1, 2);
  const vp = pg.getViewport({ scale: escala });
  p.canvas.width = Math.floor(vp.width); p.canvas.height = Math.floor(vp.height);
  await pg.render({ canvasContext: p.canvas.getContext('2d'), canvas: p.canvas, viewport: vp }).promise;
  p.el.dataset.renderizada = '1';
}

// ---------- Anotações: desenho no SVG ----------
const novoId = () => Math.random().toString(36).slice(2, 10);
const LINHA = 1.2, ASC = 0.8;

function el(tag, attrs = {}) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function elementoAnotacao(a) {
  const g = el('g', { class: 'anot', 'data-id': a.id, 'data-tipo': a.tipo });
  const txt = (x, y) => {
    const t = el('text', { x, y, fill: a.cor, 'font-size': a.tamanho, 'font-family': 'Helvetica, Arial, sans-serif' });
    a.texto.split('\n').forEach((l, k) => {
      const s = el('tspan', { x, y: y + a.tamanho * (ASC + k * LINHA) });
      s.textContent = l || ' '; t.append(s);
    });
    return t;
  };
  switch (a.tipo) {
    case 'texto': g.append(txt(a.x, a.y)); break;
    case 'cobrir':
      g.append(el('rect', { x: a.x, y: a.y, width: a.w, height: a.h, fill: '#ffffff' }));
      if (a.texto) g.append(txt(a.x + 2, a.y + 2));
      break;
    case 'destaque': g.append(el('rect', { class: 'realce', x: a.x, y: a.y, width: a.w, height: a.h, fill: a.cor, 'fill-opacity': 0.4 })); break;
    case 'retangulo': g.append(el('rect', { x: a.x, y: a.y, width: a.w, height: a.h, fill: 'none', stroke: a.cor, 'stroke-width': a.espessura })); break;
    case 'elipse': g.append(el('ellipse', { cx: a.x + a.w / 2, cy: a.y + a.h / 2, rx: a.w / 2, ry: a.h / 2, fill: 'none', stroke: a.cor, 'stroke-width': a.espessura })); break;
    case 'linha': g.append(el('line', { x1: a.x1, y1: a.y1, x2: a.x2, y2: a.y2, stroke: a.cor, 'stroke-width': a.espessura, 'stroke-linecap': 'round' })); break;
    case 'desenho': g.append(el('path', { d: caminhoSvg(a.pontos), fill: 'none', stroke: a.cor, 'stroke-width': a.espessura, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })); break;
    case 'imagem': g.append(el('image', { href: a.dataUrl, x: a.x, y: a.y, width: a.w, height: a.h, preserveAspectRatio: 'none' })); break;
  }
  // Área de clique generosa para linhas e traços finos.
  if (a.tipo === 'linha' || a.tipo === 'desenho') {
    const h = g.firstChild.cloneNode(); h.setAttribute('stroke', 'transparent'); h.setAttribute('stroke-width', Math.max(12, a.espessura + 8)); g.append(h);
  }
  return g;
}

function caminhoSvg(pts) {
  if (!pts.length) return '';
  return pts.map(([x, y], k) => `${k ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ') + (pts.length === 1 ? ' l0.01 0' : '');
}

function caixa(a) {
  if (a.tipo === 'linha') return { x: Math.min(a.x1, a.x2), y: Math.min(a.y1, a.y2), w: Math.abs(a.x2 - a.x1), h: Math.abs(a.y2 - a.y1) };
  if (a.tipo === 'desenho') {
    const xs = a.pontos.map(p => p[0]), ys = a.pontos.map(p => p[1]);
    return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  }
  return null;
}

function desenharAnotacoes() {
  estado.paginas.forEach(p => p.svg.replaceChildren());
  for (const a of estado.anotacoes) {
    const p = estado.paginas[a.pagina]; if (!p) continue;
    const g = elementoAnotacao(a);
    p.svg.append(g);
    if (a.id === estado.selecionada) {
      g.classList.add('selecionada');
      let b = caixa(a);
      if (!b) { const bb = g.getBBox(); b = { x: bb.x, y: bb.y, w: bb.width, h: bb.height }; }
      g.append(el('rect', { class: 'moldura', x: b.x - 3, y: b.y - 3, width: b.w + 6, height: b.h + 6 }));
    }
  }
  $('#bApagar').disabled = !estado.selecionada;
  $('#bDesfazer').disabled = !estado.historico.length;
  atualizarContagem();
}

function atualizarContagem() {
  const n = estado.anotacoes.length;
  $('#contaAnotacoes').textContent = `${n} anotaç${n === 1 ? 'ão' : 'ões'}`;
}

// ---------- Histórico e persistência ----------
function lembrar() {
  estado.historico.push(JSON.stringify(estado.anotacoes));
  if (estado.historico.length > 60) estado.historico.shift();
}
function desfazer() {
  if (!estado.historico.length) return;
  estado.anotacoes = JSON.parse(estado.historico.pop());
  estado.selecionada = null;
  desenharAnotacoes(); salvarDepois();
}
let tSalvar;
function salvarDepois() { clearTimeout(tSalvar); tSalvar = setTimeout(salvarAgora, 250); }
function salvarAgora() {
  clearTimeout(tSalvar);
  if (!estado.bytes) return;
  salvarSessao({ nome: estado.nome, bytes: estado.bytes, anotacoes: estado.anotacoes })
    .catch(() => avisar('Não foi possível guardar a sessão neste navegador.', true));
}
window.addEventListener('pagehide', salvarAgora);

function alterar(fn) { lembrar(); fn(); desenharAnotacoes(); salvarDepois(); }

// ---------- Interação com as páginas ----------
function pontoSvg(svg, ev) {
  const m = svg.getScreenCTM().inverse();
  const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(m);
  return [pt.x, pt.y];
}
const limitar = (v, a, b) => Math.max(a, Math.min(b, v));

function ligarEventosPagina(i) {
  const p = estado.paginas[i];
  const svg = p.svg;
  let acao = null;

  svg.addEventListener('pointerdown', ev => {
    if (ev.button !== 0) return;
    const aberto = document.querySelector('.editor-texto');
    if (aberto) { aberto.blur(); return; } // sair do editor confirma o texto
    const [x, y] = pontoSvg(svg, ev);
    const f = estado.ferramenta;
    if (f === 'selecionar') {
      const g = ev.target.closest('.anot');
      if (!g) { if (estado.selecionada) { estado.selecionada = null; desenharAnotacoes(); } return; }
      const a = estado.anotacoes.find(z => z.id === g.dataset.id);
      estado.selecionada = a.id;
      sincronizarPropriedades(a);
      acao = { tipo: 'mover', a, x0: x, y0: y, antes: JSON.stringify(estado.anotacoes), moveu: false };
      desenharAnotacoes();
    } else if (f === 'texto') {
      ev.preventDefault();
      abrirEditorTexto(i, { x, y: y - Number($('#pTamanho').value) * 0.6 });
      return;
    } else if (f === 'desenho') {
      acao = { tipo: 'desenho', a: { id: novoId(), pagina: i, tipo: 'desenho', cor: cor(), espessura: espessura(), pontos: [[x, y]] } };
    } else if (f === 'linha') {
      acao = { tipo: 'linha', a: { id: novoId(), pagina: i, tipo: 'linha', cor: cor(), espessura: espessura(), x1: x, y1: y, x2: x, y2: y } };
    } else {
      const base = { id: novoId(), pagina: i, tipo: f, cor: f === 'destaque' ? corDestaque() : cor(), espessura: espessura(), x, y, w: 0, h: 0, x0: x, y0: y };
      // Reescrita usa preto por padrão (texto de documento), a menos que o usuário tenha escolhido outra cor.
      if (f === 'cobrir') Object.assign(base, { cor: cor().toLowerCase() === COR_PADRAO ? '#111111' : cor(), texto: '', tamanho: tamanho() });
      acao = { tipo: 'caixa', a: base };
    }
    if (acao && acao.tipo !== 'mover') {
      const g = elementoAnotacao(acao.a); g.classList.add('rascunho'); svg.append(g); acao.g = g;
    }
    svg.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });

  svg.addEventListener('pointermove', ev => {
    if (!acao) return;
    const [x, y] = pontoSvg(svg, ev);
    const a = acao.a;
    if (acao.tipo === 'mover') {
      const dx = x - acao.x0, dy = y - acao.y0;
      if (Math.abs(dx) + Math.abs(dy) < 0.5) return;
      acao.x0 = x; acao.y0 = y; acao.moveu = true;
      deslocar(a, dx, dy, p);
      desenharAnotacoes();
      return;
    }
    if (acao.tipo === 'desenho') a.pontos.push([limitar(x, 0, p.w), limitar(y, 0, p.h)]);
    else if (acao.tipo === 'linha') { a.x2 = limitar(x, 0, p.w); a.y2 = limitar(y, 0, p.h); }
    else {
      const cx = limitar(x, 0, p.w), cy = limitar(y, 0, p.h);
      a.x = Math.min(a.x0, cx); a.y = Math.min(a.y0, cy); a.w = Math.abs(cx - a.x0); a.h = Math.abs(cy - a.y0);
    }
    const g = elementoAnotacao(a); acao.g.replaceWith(g); acao.g = g;
  });

  const terminar = () => {
    if (!acao) return;
    const { tipo, a } = acao; acao.g?.remove();
    if (tipo === 'mover') {
      if (acao.moveu) { estado.historico.push(acao.antes); salvarDepois(); desenharAnotacoes(); }
      acao = null; return;
    }
    acao = null;
    const pequeno = tipo === 'caixa' ? (a.w < 4 || a.h < 4)
      : tipo === 'linha' ? Math.hypot(a.x2 - a.x1, a.y2 - a.y1) < 4 : false;
    if (pequeno) return;
    delete a.x0; delete a.y0;
    alterar(() => estado.anotacoes.push(a));
    if (a.tipo === 'cobrir') abrirEditorTexto(i, a, a);
  };
  svg.addEventListener('pointerup', terminar);
  svg.addEventListener('pointercancel', terminar);

  svg.addEventListener('dblclick', ev => {
    const g = ev.target.closest('.anot');
    if (!g) return;
    const a = estado.anotacoes.find(z => z.id === g.dataset.id);
    if (a && (a.tipo === 'texto' || a.tipo === 'cobrir')) abrirEditorTexto(i, a, a);
  });
}

function deslocar(a, dx, dy, p) {
  if (a.tipo === 'linha') { a.x1 += dx; a.x2 += dx; a.y1 += dy; a.y2 += dy; }
  else if (a.tipo === 'desenho') a.pontos = a.pontos.map(([x, y]) => [x + dx, y + dy]);
  else { a.x = limitar(a.x + dx, -(a.w || 0) + 5, p.w - 5); a.y = limitar(a.y + dy, -(a.h || 0) + 5, p.h - 5); }
}

// Editor de texto sobreposto (textarea HTML) — confirma com Enter ou ao sair; Shift+Enter quebra linha.
function abrirEditorTexto(i, pos, existente = null) {
  const p = estado.paginas[i];
  const k = p.el.clientWidth / p.w;
  const tam = existente?.tamanho ?? tamanho();
  const ta = document.createElement('textarea');
  ta.className = 'editor-texto';
  ta.setAttribute('aria-label', 'Texto da anotação');
  ta.value = existente?.texto ?? '';
  const x = existente?.tipo === 'cobrir' ? existente.x + 2 : pos.x;
  const y = existente?.tipo === 'cobrir' ? existente.y + 2 : pos.y;
  Object.assign(ta.style, {
    // Ajuste fino: a linha de base da textarea (line-height 1.2) fica ~0,2·tamanho abaixo da do SVG.
    left: `${x * k - 2}px`, top: `${(y - 0.2 * tam) * k - 2}px`, fontSize: `${tam * k}px`,
    color: existente?.cor ?? cor(), maxWidth: `${(p.w - x) * k}px`,
  });
  if (existente?.tipo === 'cobrir') { ta.style.width = `${existente.w * k}px`; ta.style.height = `${existente.h * k}px`; }
  p.el.append(ta);
  if (existente) { estado.selecionada = null; const g = p.svg.querySelector(`[data-id="${existente.id}"] text`); g?.setAttribute('visibility', 'hidden'); }
  setTimeout(() => ta.focus(), 0);
  let feito = false;
  const confirmar = (cancelar = false) => {
    if (feito) return; feito = true;
    const texto = ta.value.replace(/\s+$/, '');
    ta.remove();
    if (cancelar) { desenharAnotacoes(); return; }
    if (existente) {
      if (existente.tipo === 'texto' && !texto) alterar(() => { estado.anotacoes = estado.anotacoes.filter(z => z !== existente); });
      else if (texto !== existente.texto) alterar(() => { existente.texto = texto; });
      else desenharAnotacoes();
    } else if (texto) {
      const a = { id: novoId(), pagina: i, tipo: 'texto', cor: cor(), tamanho: tam, x, y, texto };
      alterar(() => estado.anotacoes.push(a));
    }
  };
  ta.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); confirmar(); }
    if (ev.key === 'Escape') { ev.preventDefault(); confirmar(true); }
    ev.stopPropagation();
  });
  ta.addEventListener('blur', () => confirmar());
}

// ---------- Ferramentas e propriedades ----------
const cor = () => $('#pCor').value;
const COR_PADRAO = '#d0312d';
const corDestaque = () => (cor().toLowerCase() === COR_PADRAO ? '#ffe14d' : cor());
const espessura = () => Number($('#pEspessura').value);
const tamanho = () => Number($('#pTamanho').value);

function escolherFerramenta(f) {
  estado.ferramenta = f;
  $$('.ferr[data-ferr]').forEach(b => b.classList.toggle('ativa', b.dataset.ferr === f));
  estado.paginas.forEach(p => { p.svg.dataset.ferr = f; });
  if (f !== 'selecionar' && estado.selecionada) { estado.selecionada = null; desenharAnotacoes(); }
}

function sincronizarPropriedades(a) {
  if (a.cor && /^#[0-9a-f]{6}$/i.test(a.cor)) $('#pCor').value = a.cor;
  if (a.espessura) $('#pEspessura').value = a.espessura;
  if (a.tamanho) $('#pTamanho').value = a.tamanho;
}

function aplicarPropriedade(campo, valor) {
  const a = estado.anotacoes.find(z => z.id === estado.selecionada);
  if (!a || a.tipo === 'imagem') return;
  if (campo === 'tamanho' && !('tamanho' in a)) return;
  if (campo === 'espessura' && ['texto', 'destaque', 'cobrir'].includes(a.tipo)) return;
  alterar(() => { a[campo] = valor; });
}

function apagarSelecionada() {
  if (!estado.selecionada) return;
  alterar(() => { estado.anotacoes = estado.anotacoes.filter(z => z.id !== estado.selecionada); estado.selecionada = null; });
}

// Página mais visível na tela — destino da imagem inserida.
function paginaVisivel() {
  let melhor = 0, area = -1;
  estado.paginas.forEach((p, i) => {
    const r = p.el.getBoundingClientRect();
    const vis = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
    if (vis > area) { area = vis; melhor = i; }
  });
  return melhor;
}

async function inserirImagem(arq) {
  if (!arq) return;
  let dataUrl = await new Promise((ok, erro) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = erro; r.readAsDataURL(arq); });
  const img = await new Promise((ok, erro) => { const im = new Image(); im.onload = () => ok(im); im.onerror = erro; im.src = dataUrl; })
    .catch(() => null);
  if (!img) { avisar('Imagem não reconhecida.', true); return; }
  if (!/^data:image\/(png|jpeg)/.test(dataUrl)) { // pdf-lib só embute PNG e JPEG
    const c = Object.assign(document.createElement('canvas'), { width: img.naturalWidth, height: img.naturalHeight });
    c.getContext('2d').drawImage(img, 0, 0); dataUrl = c.toDataURL('image/png');
  }
  const i = paginaVisivel(), p = estado.paginas[i];
  const w = Math.min(img.naturalWidth, p.w * 0.4), h = w * img.naturalHeight / img.naturalWidth;
  const a = { id: novoId(), pagina: i, tipo: 'imagem', dataUrl, x: (p.w - w) / 2, y: Math.max(10, (p.h - h) / 3), w, h };
  escolherFerramenta('selecionar');
  alterar(() => { estado.anotacoes.push(a); estado.selecionada = a.id; });
  avisar('Imagem inserida. Arraste para posicionar.');
}

// ---------- Baixar PDF editado ----------
async function baixarPdfEditado() {
  carregando(true);
  try {
    const bytes = await gerarPdfAnotado(estado.bytes, estado.paginas, estado.anotacoes);
    baixar(new Blob([bytes], { type: 'application/pdf' }), `${nomeBase()}-editado.pdf`);
    avisar('PDF editado gerado.');
  } catch (e) {
    avisar(`Falha ao gerar o PDF: ${e.message}`, true);
  } finally { carregando(false); }
}

// ---------- Modo Extrair ----------
function mudarModo(m) {
  $('#modoEditar').hidden = m !== 'editar';
  $('#modoExtrair').hidden = m !== 'extrair';
  $('#abaEditar').classList.toggle('ativa', m === 'editar');
  $('#abaExtrair').classList.toggle('ativa', m === 'extrair');
  $('#abaEditar').setAttribute('aria-selected', m === 'editar');
  $('#abaExtrair').setAttribute('aria-selected', m === 'extrair');
}

async function montarMiniaturas() {
  const cont = $('#miniaturas');
  cont.replaceChildren();
  for (let i = 0; i < estado.doc.numPages; i++) {
    const lab = document.createElement('label');
    lab.className = 'mini'; lab.id = `mini-${i + 1}`;
    const chk = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'sel-pagina', value: i, checked: estado.selecaoExtrair.has(i) });
    chk.setAttribute('aria-label', `Página ${i + 1}`);
    chk.addEventListener('change', () => { chk.checked ? estado.selecaoExtrair.add(i) : estado.selecaoExtrair.delete(i); atualizarSelecao(); });
    const c = document.createElement('canvas');
    lab.append(chk, c, Object.assign(document.createElement('span'), { textContent: `Página ${i + 1}` }));
    cont.append(lab);
  }
  atualizarSelecao();
  const doc = estado.doc;
  try {
    for (let i = 0; i < doc.numPages; i++) {
      if (estado.doc !== doc) return;
      const pg = await doc.getPage(i + 1);
      const vp = pg.getViewport({ scale: 160 / pg.getViewport({ scale: 1 }).width });
      const c = $(`#mini-${i + 1} canvas`); if (!c) return;
      c.width = vp.width; c.height = vp.height;
      await pg.render({ canvasContext: c.getContext('2d'), canvas: c, viewport: vp }).promise;
    }
  } catch (e) {
    if (estado.doc === doc) throw e; // documento fechado/trocado no meio: ignora
  }
}

function atualizarSelecao() {
  $$('.sel-pagina').forEach(chk => { chk.checked = estado.selecaoExtrair.has(Number(chk.value)); chk.closest('.mini').classList.toggle('marcada', chk.checked); });
  const n = estado.selecaoExtrair.size;
  $('#contaSel').textContent = `${n} de ${estado.doc?.numPages ?? 0} selecionada${n === 1 ? '' : 's'}`;
}

// "1-3, 5" -> {0,1,2,4}
function lerIntervalo(txt, total) {
  const s = new Set();
  for (const parte of txt.split(/[,;\s]+/).filter(Boolean)) {
    const m = parte.match(/^(\d+)(?:-(\d+))?$/);
    if (!m) throw new Error(`Trecho inválido: "${parte}"`);
    let a = Number(m[1]), b = Number(m[2] ?? m[1]);
    if (a > b) [a, b] = [b, a];
    if (a < 1 || b > total) throw new Error(`Páginas fora do documento (1 a ${total})`);
    for (let k = a; k <= b; k++) s.add(k - 1);
  }
  return s;
}

const selecionadas = () => [...estado.selecaoExtrair].sort((a, b) => a - b);
function exigirSelecao() {
  const s = selecionadas();
  if (!s.length) avisar('Escolha ao menos uma página.', true);
  return s;
}

let textosExtraidos = [];
async function extrairTexto() {
  const sel = exigirSelecao(); if (!sel.length) return;
  carregando(true);
  try {
    textosExtraidos = [];
    for (const i of sel) textosExtraidos.push({ pagina: i + 1, texto: await textoDaPagina(await estado.doc.getPage(i + 1)) });
    $('#textoCompleto').value = textoCompleto();
    const lista = $('#textoPorPagina'); lista.replaceChildren();
    for (const t of textosExtraidos) {
      const box = document.createElement('article');
      box.className = 'texto-pagina'; box.id = `texto-p${t.pagina}`;
      box.innerHTML = `<header><b>Página ${t.pagina}</b><button class="botao fantasma copiar">Copiar</button><button class="botao fantasma baixar-txt">Baixar .txt</button></header><pre></pre>`;
      box.querySelector('pre').textContent = t.texto || '(sem texto nesta página)';
      box.querySelector('.copiar').addEventListener('click', () => copiar(t.texto));
      box.querySelector('.baixar-txt').addEventListener('click', () => baixar(new Blob([t.texto], { type: 'text/plain;charset=utf-8' }), `${nomeBase()}-pagina-${t.pagina}.txt`));
      lista.append(box);
    }
    $('#saidaTexto').hidden = false;
    const vazio = textosExtraidos.every(t => !t.texto.trim());
    avisar(vazio ? 'Nenhum texto encontrado. O PDF pode ser digitalizado (imagem).' : `Texto extraído de ${sel.length} página(s).`, vazio);
  } finally { carregando(false); }
}
const textoCompleto = () => textosExtraidos.map(t => `--- Página ${t.pagina} ---\n${t.texto}`).join('\n\n') + '\n';

async function copiar(texto) {
  try { await navigator.clipboard.writeText(texto); avisar('Texto copiado.'); }
  catch {
    const ta = $('#textoCompleto');
    const antes = ta.value; ta.value = texto; ta.select();
    const ok = document.execCommand('copy');
    ta.value = antes;
    avisar(ok ? 'Texto copiado.' : 'Não foi possível copiar automaticamente. Selecione o texto e copie.', !ok);
  }
}

async function extrairPaginas() {
  const sel = exigirSelecao(); if (!sel.length) return;
  carregando(true);
  try {
    let origem = estado.bytes;
    if ($('#incluirAnotacoes').checked && estado.anotacoes.some(a => sel.includes(a.pagina)))
      origem = await gerarPdfAnotado(estado.bytes, estado.paginas, estado.anotacoes);
    const bytes = await gerarPdfComPaginas(origem, sel);
    baixar(new Blob([bytes], { type: 'application/pdf' }), `${nomeBase()}-paginas-${descreverPaginas(sel)}.pdf`);
    avisar(`Novo PDF com ${sel.length} página(s) gerado.`);
  } catch (e) { avisar(`Falha ao extrair páginas: ${e.message}`, true); }
  finally { carregando(false); }
}

function descreverPaginas(sel) {
  const partes = []; let ini = sel[0], ant = sel[0];
  for (const n of [...sel.slice(1), Infinity]) {
    if (n === ant + 1) { ant = n; continue; }
    partes.push(ini === ant ? `${ini + 1}` : `${ini + 1}-${ant + 1}`); ini = ant = n;
  }
  return partes.join('_');
}

function itemGaleria(url, legenda, nomeArq) {
  const item = document.createElement('figure');
  item.className = 'item-imagem'; item.style.margin = 0;
  const img = Object.assign(document.createElement('img'), { src: url, alt: legenda });
  const cap = Object.assign(document.createElement('figcaption'), { textContent: legenda });
  const b = Object.assign(document.createElement('button'), { className: 'botao fantasma baixar-imagem', textContent: 'Baixar PNG' });
  b.addEventListener('click', async () => baixar(await (await fetch(url)).blob(), nomeArq));
  item.append(img, cap, b);
  return item;
}

async function extrairImagens() {
  const sel = exigirSelecao(); if (!sel.length) return;
  carregando(true);
  const gal = $('#galeriaImagens'); gal.replaceChildren();
  try {
    let total = 0;
    for (const i of sel) {
      const imgs = await imagensDaPagina(await estado.doc.getPage(i + 1), pdfjs.OPS);
      imgs.forEach((im, k) => {
        total++;
        gal.append(itemGaleria(im.url, `Página ${i + 1} · ${im.largura}×${im.altura} px`, `${nomeBase()}-p${i + 1}-imagem-${k + 1}.png`));
      });
    }
    $('#resumoImagens').textContent = total
      ? `${total} imagem${total > 1 ? 'ns' : ''} embutida${total > 1 ? 's' : ''} encontrada${total > 1 ? 's' : ''}.`
      : 'Nenhuma imagem embutida nas páginas escolhidas.';
  } catch (e) { avisar(`Falha ao extrair imagens: ${e.message}`, true); }
  finally { carregando(false); }
}

async function paginasComoPng() {
  const sel = exigirSelecao(); if (!sel.length) return;
  carregando(true);
  const gal = $('#galeriaImagens'); gal.replaceChildren();
  try {
    for (const i of sel) {
      const url = await paginaComoPng(await estado.doc.getPage(i + 1), estado.anotacoes.filter(a => a.pagina === i), estado.paginas[i], elementoAnotacao);
      gal.append(itemGaleria(url, `Página ${i + 1} (página inteira)`, `${nomeBase()}-pagina-${i + 1}.png`));
    }
    $('#resumoImagens').textContent = `${sel.length} página(s) convertida(s) em PNG. Use “Baixar PNG” em cada uma.`;
  } catch (e) { avisar(`Falha ao gerar PNG: ${e.message}`, true); }
  finally { carregando(false); }
}

// ---------- Ligações ----------
$('#arquivoPdf').addEventListener('change', e => { abrirArquivo(e.target.files[0]); e.target.value = ''; });
$('#arquivoImagem').addEventListener('change', e => { inserirImagem(e.target.files[0]); e.target.value = ''; });
const zona = $('#zonaSoltar');
for (const ev of ['dragenter', 'dragover']) document.addEventListener(ev, e => { e.preventDefault(); zona.classList.add('sobre'); });
document.addEventListener('dragleave', e => { if (!e.relatedTarget) zona.classList.remove('sobre'); });
document.addEventListener('drop', e => {
  e.preventDefault(); zona.classList.remove('sobre');
  const arq = [...(e.dataTransfer?.files || [])].find(f => /pdf/i.test(f.type) || /\.pdf$/i.test(f.name));
  if (arq) abrirArquivo(arq);
});
zona.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#arquivoPdf').click(); } });

$$('.ferr[data-ferr]').forEach(b => b.addEventListener('click', () => escolherFerramenta(b.dataset.ferr)));
$('#fImagem').addEventListener('click', () => $('#arquivoImagem').click());
$('#pCor').addEventListener('change', e => aplicarPropriedade('cor', e.target.value));
$('#pEspessura').addEventListener('change', e => aplicarPropriedade('espessura', Number(e.target.value)));
$('#pTamanho').addEventListener('change', e => aplicarPropriedade('tamanho', Number(e.target.value)));
$('#bApagar').addEventListener('click', apagarSelecionada);
$('#bDesfazer').addEventListener('click', desfazer);
$('#bBaixarPdf').addEventListener('click', baixarPdfEditado);
$('#bFechar').addEventListener('click', fechar);
$('#abaEditar').addEventListener('click', () => mudarModo('editar'));
$('#abaExtrair').addEventListener('click', () => mudarModo('extrair'));
$('#bTodas').addEventListener('click', () => { estado.selecaoExtrair = new Set(estado.paginas.map((_, i) => i)); atualizarSelecao(); });
$('#bNenhuma').addEventListener('click', () => { estado.selecaoExtrair.clear(); atualizarSelecao(); });
$('#bAplicarIntervalo').addEventListener('click', () => {
  try { estado.selecaoExtrair = lerIntervalo($('#intervalo').value, estado.doc.numPages); atualizarSelecao(); }
  catch (e) { avisar(e.message, true); }
});
$('#intervalo').addEventListener('keydown', e => { if (e.key === 'Enter') $('#bAplicarIntervalo').click(); });
$('#bExtrairTexto').addEventListener('click', extrairTexto);
$('#bCopiarTexto').addEventListener('click', () => copiar(textoCompleto()));
$('#bBaixarTxt').addEventListener('click', () => baixar(new Blob([textoCompleto()], { type: 'text/plain;charset=utf-8' }), `${nomeBase()}-texto.txt`));
$('#bExtrairPaginas').addEventListener('click', extrairPaginas);
$('#bExtrairImagens').addEventListener('click', extrairImagens);
$('#bPaginasPng').addEventListener('click', paginasComoPng);

const ATALHOS = { v: 'selecionar', t: 'texto', h: 'destaque', d: 'desenho', r: 'retangulo', e: 'elipse', l: 'linha' };
document.addEventListener('keydown', e => {
  if (!estado.doc || $('#modoEditar').hidden || e.target.matches('input, textarea, select')) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); desfazer(); return; }
  if (e.key === 'Delete' || e.key === 'Backspace') { if (estado.selecionada) { e.preventDefault(); apagarSelecionada(); } return; }
  if (!e.ctrlKey && !e.metaKey && !e.altKey && ATALHOS[e.key.toLowerCase()]) escolherFerramenta(ATALHOS[e.key.toLowerCase()]);
});

let tResize, larguraAnterior = innerWidth;
window.addEventListener('resize', () => {
  clearTimeout(tResize);
  tResize = setTimeout(async () => {
    if (!estado.doc || Math.abs(innerWidth - larguraAnterior) < 80) return;
    larguraAnterior = innerWidth;
    for (let i = 0; i < estado.paginas.length; i++) await renderizarPagina(i);
  }, 300);
});

// Restaura a última sessão (PDF + anotações) guardada no IndexedDB deste navegador.
(async () => {
  const s = await lerSessao().catch(() => null);
  if (s?.bytes) {
    await carregarDocumento(s.nome, new Uint8Array(s.bytes), s.anotacoes || []);
    avisar('Sessão anterior restaurada.');
  }
  document.body.dataset.pronto = '1';
})();
