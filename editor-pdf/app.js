// Folha Clara — editor e extrator de PDF que roda só no navegador.
// Renderização e extração: pdf.js (Apache-2.0). Gravação: pdf-lib (MIT).
import * as pdfjs from './vendor/pdfjs/pdf.min.mjs';
import { gerarPdfAnotado, gerarPdfComPaginas } from './exportar.js';
import { textoDaPagina, imagensDaPagina, paginaComoPng, paginaComoJpeg } from './extrair.js';
import {
  linhasDoPdf, linhasDoOcr, mesclarLinhas, amostrarFundo, amostrarCorTexto, estenderPelaTinta, medirTinta, corDoFundo, familiaCss, fracaoBase,
  tamanhoPadrao, cssFontesEmbutidas, esquerdaDoTexto, baseDoTexto, larguraUtil, margemDoTexto, LINHA,
} from './texto.js';
import { reconhecerCanvas } from './ocr.js';
import { salvarSessao, lerSessao, apagarSessao } from './sessao.js';

pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/pdf.worker.min.mjs', import.meta.url).href;
const OPCOES_PDFJS = {
  standardFontDataUrl: new URL('./vendor/pdfjs/standard_fonts/', import.meta.url).href,
  cMapUrl: new URL('./vendor/pdfjs/cmaps/', import.meta.url).href,
  cMapPacked: true,
  verbosity: 0,
  fontExtraProperties: true, // expõe o nome real da fonte (usado para detectar negrito/itálico e casar com a fonte padrão)
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
  editor: null,         // editor de texto aberto no momento
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
    Object.assign(estado, { nome, bytes, doc, tarefa, anotacoes, selecionada: null, historico: [], paginas: [], editor: null });
    estado.selecaoExtrair = new Set(Array.from({ length: doc.numPages }, (_, i) => i));
    $('#telaInicial').hidden = true;
    $('#abaEditar').disabled = $('#abaExtrair').disabled = false;
    $('#bFechar').hidden = false;
    $('#nomeDoc').textContent = nome;
    $('#contaPaginas').textContent = `${doc.numPages} página${doc.numPages > 1 ? 's' : ''}`;
    await montarPaginas();
    escolherFerramenta(estado.ferramenta); // mantém a ferramenta atual no novo documento
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
  Object.assign(estado, { nome: '', bytes: null, doc: null, tarefa: null, paginas: [], anotacoes: [], selecionada: null, historico: [], editor: null });
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

function el(tag, attrs = {}) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

// Fundo de um bloco (cobrir/edição): cor única, degradê vertical ou colunas de degradês verticais, amostrados do documento.
function gradienteVertical(g, id, cores) {
  const grad = el('linearGradient', { id, x1: 0, y1: 0, x2: 0, y2: 1 });
  const n = cores.length;
  grad.append(el('stop', { offset: 0, 'stop-color': cores[0] }));
  cores.forEach((c, k) => grad.append(el('stop', { offset: (k + 0.5) / n, 'stop-color': c })));
  grad.append(el('stop', { offset: 1, 'stop-color': cores[n - 1] }));
  g.querySelector('defs').append(grad);
  return `url(#${id})`;
}
function fundoSvg(g, a) {
  const fundo = a.fundo || '#ffffff';
  g.append(el('defs'));
  if (typeof fundo === 'string') { g.append(el('rect', { class: 'fundo', x: a.x, y: a.y, width: a.w, height: a.h, fill: fundo })); return; }
  if (Array.isArray(fundo[0])) { // colunas: cada uma vai do seu x até a borda direita (sem emendas); a seguinte pinta por cima
    const n = fundo.length;
    fundo.forEach((col, c) => {
      const x = a.x + a.w * c / n;
      g.append(el('rect', { class: 'fundo', x, y: a.y, width: a.x + a.w - x, height: a.h, fill: col.length > 1 ? gradienteVertical(g, `gr-${a.id}-${c}`, col) : col[0] }));
    });
    return;
  }
  g.append(el('rect', { class: 'fundo', x: a.x, y: a.y, width: a.w, height: a.h, fill: fundo.length > 1 ? gradienteVertical(g, `gr-${a.id}`, fundo) : fundo[0] }));
}

// Texto de uma anotação (fonte, negrito, itálico, alinhamento e linha de base conforme os campos da anotação).
function textoSvg(a) {
  const util = larguraUtil(a), L = esquerdaDoTexto(a), base0 = baseDoTexto(a);
  const alinhar = util ? a.alinhar : 'esq';
  const x = alinhar === 'centro' ? L + util / 2 : alinhar === 'dir' ? L + util : L;
  const t = el('text', {
    x, y: base0, fill: a.cor, 'font-size': a.tamanho, 'font-family': familiaCss(a.fonte || 'helvetica'),
    'font-weight': a.negrito ? 700 : 400, 'font-style': a.italico ? 'italic' : 'normal',
    'text-anchor': alinhar === 'centro' ? 'middle' : alinhar === 'dir' ? 'end' : 'start',
    'xml:space': 'preserve',
  });
  a.texto.split('\n').forEach((l, k) => {
    const s = el('tspan', { x, y: base0 + k * LINHA * a.tamanho });
    s.textContent = l || ' '; t.append(s);
  });
  return t;
}

function elementoAnotacao(a) {
  const g = el('g', { class: 'anot', 'data-id': a.id, 'data-tipo': a.tipo });
  switch (a.tipo) {
    case 'texto': g.append(textoSvg(a)); break;
    case 'cobrir': case 'edicao':
      fundoSvg(g, a);
      if (a.texto) g.append(textoSvg(a));
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
  desenharLinhasDetectadas();
  for (const a of estado.anotacoes) {
    const p = estado.paginas[a.pagina]; if (!p) continue;
    const g = elementoAnotacao(a);
    p.svg.append(g);
    if (estado.editor && estado.editor.a === a) g.querySelector('text')?.setAttribute('visibility', 'hidden'); // quem mostra o texto é o editor
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
  atualizarAvisoRemocao();
}

// Páginas em que algum texto foi coberto/reescrito (candidatas a virar imagem na opção "Remover de vez").
const paginasComTextoCoberto = () => [...new Set(estado.anotacoes.filter(a => a.tipo === 'edicao' || a.tipo === 'cobrir').map(a => a.pagina))].sort((x, y) => x - y);
function atualizarAvisoRemocao() {
  const pgs = paginasComTextoCoberto();
  $('#linhaRemocao').hidden = !pgs.length;
  if (!pgs.length) return;
  const rem = $('#removerTexto').checked;
  $('#avisoRemocao').textContent = rem
    ? `Ao baixar, ${pgs.length === 1 ? 'a página' : 'as páginas'} ${pgs.map(n => n + 1).join(', ')} ${pgs.length === 1 ? 'será gravada' : 'serão gravadas'} como imagem: o texto antigo deixa de existir no arquivo, mas essa${pgs.length === 1 ? '' : 's'} página${pgs.length === 1 ? '' : 's'} também deixa${pgs.length === 1 ? '' : 'm'} de ter texto selecionável.`
    : 'Atenção: cobrir não apaga. O texto antigo continua dentro do arquivo e pode ser copiado em qualquer leitor de PDF.';
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
const TIPOS_TEXTO = ['texto', 'cobrir', 'edicao'];

function ligarEventosPagina(i) {
  const p = estado.paginas[i];
  const svg = p.svg;
  let acao = null;

  svg.addEventListener('pointerdown', ev => {
    if (ev.button !== 0) return;
    if (estado.editor) { estado.editor.confirmar(); return; } // clicar fora do editor confirma o texto
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
    } else if (f === 'editartexto') {
      // Clique numa linha detectada edita a linha; arrastar um retângulo marca à mão um texto que não foi detectado.
      acao = { tipo: 'area', x0: x, y0: y, cx: ev.clientX, cy: ev.clientY, alvo: ev.target, arrastou: false, rect: null };
    } else if (f === 'texto') {
      ev.preventDefault();
      abrirEditorTexto(i, novoTexto(i, x, y), { emLista: false });
      return;
    } else if (f === 'desenho') {
      acao = { tipo: 'desenho', a: { id: novoId(), pagina: i, tipo: 'desenho', cor: cor(), espessura: espessura(), pontos: [[x, y]] } };
    } else if (f === 'linha') {
      acao = { tipo: 'linha', a: { id: novoId(), pagina: i, tipo: 'linha', cor: cor(), espessura: espessura(), x1: x, y1: y, x2: x, y2: y } };
    } else {
      const base = { id: novoId(), pagina: i, tipo: f, cor: f === 'destaque' ? corDestaque() : cor(), espessura: espessura(), x, y, w: 0, h: 0, x0: x, y0: y };
      if (f === 'cobrir') Object.assign(base, { texto: '' }, propsTexto(i));
      acao = { tipo: 'caixa', a: base };
    }
    if (acao && acao.tipo !== 'mover' && acao.tipo !== 'area') {
      const g = elementoAnotacao(acao.a); g.classList.add('rascunho'); svg.append(g); acao.g = g;
    }
    svg.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });

  svg.addEventListener('pointermove', ev => {
    if (!acao) {
      if (estado.ferramenta === 'editartexto' && !estado.editor) { const [x, y] = pontoSvg(svg, ev); destacarLinha(i, x, y); }
      return;
    }
    const [x, y] = pontoSvg(svg, ev);
    const a = acao.a;
    if (acao.tipo === 'area') {
      if (!acao.arrastou && Math.hypot(ev.clientX - acao.cx, ev.clientY - acao.cy) < 6) return;
      acao.arrastou = true;
      if (!acao.rect) { acao.rect = el('rect', { class: 'area-selecao' }); svg.append(acao.rect); }
      const cx = limitar(x, 0, p.w), cy = limitar(y, 0, p.h);
      acao.caixa = { x: Math.min(acao.x0, cx), y: Math.min(acao.y0, cy), w: Math.abs(cx - acao.x0), h: Math.abs(cy - acao.y0) };
      for (const [k, v] of Object.entries(acao.caixa)) acao.rect.setAttribute(k === 'w' ? 'width' : k === 'h' ? 'height' : k, v);
      return;
    }
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
  svg.addEventListener('pointerleave', () => { if (estado.ferramenta === 'editartexto') destacarLinha(i, -1e6, -1e6); });

  const terminar = () => {
    if (!acao) return;
    const { tipo, a } = acao; acao.g?.remove();
    if (tipo === 'area') {
      acao.rect?.remove();
      const { arrastou, caixa: cx, alvo, x0, y0 } = acao; acao = null;
      if (!arrastou) clicarParaEditar(i, { target: alvo }, x0, y0);
      else if (cx.w >= 6 && cx.h >= 6) iniciarEdicaoManual(i, cx);
      return;
    }
    if (tipo === 'mover') {
      if (acao.moveu) { estado.historico.push(acao.antes); salvarDepois(); desenharAnotacoes(); }
      acao = null; return;
    }
    acao = null;
    const pequeno = tipo === 'caixa' ? (a.w < 4 || a.h < 4)
      : tipo === 'linha' ? Math.hypot(a.x2 - a.x1, a.y2 - a.y1) < 4 : false;
    if (pequeno) return;
    delete a.x0; delete a.y0;
    if (a.tipo === 'cobrir') { // em vez de branco, cobre com o fundo amostrado ao redor da área
      const k = p.canvas.width / p.w;
      a.fundo = amostrarFundo(p.canvas, { x0: a.x * k, y0: a.y * k, x1: (a.x + a.w) * k, y1: (a.y + a.h) * k });
    }
    const antes = JSON.stringify(estado.anotacoes);
    estado.anotacoes.push(a);
    if (a.tipo === 'cobrir') { abrirEditorTexto(i, a, { antes }); return; }
    estado.historico.push(antes); desenharAnotacoes(); salvarDepois();
  };
  svg.addEventListener('pointerup', terminar);
  svg.addEventListener('pointercancel', terminar);

  svg.addEventListener('dblclick', ev => {
    const g = ev.target.closest('.anot');
    if (!g) return;
    const a = estado.anotacoes.find(z => z.id === g.dataset.id);
    if (a && TIPOS_TEXTO.includes(a.tipo)) abrirEditorTexto(i, a);
  });
}

function deslocar(a, dx, dy, p) {
  if (a.tipo === 'linha') { a.x1 += dx; a.x2 += dx; a.y1 += dy; a.y2 += dy; }
  else if (a.tipo === 'desenho') a.pontos = a.pontos.map(([x, y]) => [x + dx, y + dy]);
  else if (a.tipo === 'edicao') { a.tx = (a.tx || 0) + dx; a.ty = (a.ty || 0) + dy; } // só o texto novo anda; a cobertura fica sobre o texto antigo
  else {
    a.x = limitar(a.x + dx, -(a.w || 0) + 5, p.w - 5); a.y = limitar(a.y + dy, -(a.h || 0) + 5, p.h - 5);
    if (a.base != null) a.base += dy;
  }
}

// ---------- Editar texto: linhas detectadas ----------
// Linhas da camada de texto do PDF (pdf.js); se a página for imagem, vêm do OCR (sob demanda).
function garantirLinhas(i) {
  const p = estado.paginas[i];
  p.promessaLinhas ??= (async () => {
    const pg = await estado.doc.getPage(i + 1);
    p.linhasPdf = await linhasDoPdf(pg, p.transform);
    p.linhas = mesclarLinhas(p.linhasPdf, p.linhasOcr || []);
  })();
  return p.promessaLinhas;
}

const linhasJaEditadas = idx => new Set(estado.anotacoes.filter(a => a.tipo === 'edicao' && a.pagina === idx).map(a => a.linhaId));

function desenharLinhasDetectadas() {
  estado.paginas.forEach((p, idx) => {
    atualizarCartaoOcr(idx);
    if (estado.ferramenta !== 'editartexto' || !p.linhas) return;
    const feitas = linhasJaEditadas(idx);
    const g = el('g', { class: 'linhas-detectadas' });
    for (const l of p.linhas) {
      if (feitas.has(l.id)) continue;
      g.append(el('rect', { class: `linha-detectada${p.hoverId === l.id ? ' ativa' : ''}`, 'data-lid': l.id, 'data-origem': l.origem, x: l.x - 1, y: l.y - 1, width: l.w + 2, height: l.h + 2, rx: 2 }));
    }
    p.svg.append(g);
  });
}

function linhaEm(idx, x, y) {
  const p = estado.paginas[idx]; if (!p.linhas) return null;
  const feitas = linhasJaEditadas(idx);
  let melhor = null, area = Infinity;
  for (const l of p.linhas) {
    if (feitas.has(l.id)) continue;
    const tol = 2 + 0.08 * l.tamanho;
    if (x >= l.x - tol && x <= l.x + l.w + tol && y >= l.y - tol && y <= l.y + l.h + tol && l.w * l.h < area) { melhor = l; area = l.w * l.h; }
  }
  return melhor;
}

function destacarLinha(idx, x, y) {
  const p = estado.paginas[idx];
  const id = linhaEm(idx, x, y)?.id ?? null;
  if (p.hoverId === id) return;
  p.hoverId = id;
  p.svg.querySelectorAll('.linha-detectada').forEach(r => r.classList.toggle('ativa', r.dataset.lid === id));
  p.svg.style.cursor = id ? 'pointer' : '';
}

async function clicarParaEditar(i, ev, x, y) {
  const g = ev.target.closest('.anot');
  if (g) {
    const a = estado.anotacoes.find(z => z.id === g.dataset.id);
    if (a && TIPOS_TEXTO.includes(a.tipo)) { abrirEditorTexto(i, a); return; }
  }
  const p = estado.paginas[i];
  if (!p.linhas) await garantirLinhas(i);
  const l = linhaEm(i, x, y);
  if (l) { iniciarEdicaoLinha(i, l); return; }
  if (!p.linhas.length && !p.ocrFeito) avisar('Esta página não tem texto selecionável. Use “Reconhecer texto desta página (OCR)”.', true);
}

// Cria a anotação "edicao" sobre a linha: fundo e cor amostrados do canvas, tamanho e peso vindos da linha.
function iniciarEdicaoLinha(i, l) {
  const p = estado.paginas[i];
  const padV = Math.max(1.2, 0.08 * l.tamanho), padH = padV * 1.5;
  let cob = { x: Math.max(0, l.x - padH), y: Math.max(0, l.y - padV), w: l.w + 2 * padH, h: l.h + 2 * padV };
  const k = p.canvas.width / p.w;
  const emPx = c => ({ x0: c.x * k, y0: c.y * k, x1: (c.x + c.w) * k, y1: (c.y + c.h) * k });
  // 1) fundo ao redor da caixa; 2) estende a caixa por acentos/cedilha que ficaram de fora; 3) amostra o fundo de novo.
  const fundo0 = amostrarFundo(p.canvas, emPx(cob));
  const ext = estenderPelaTinta(p.canvas, emPx(cob), fundo0, Math.round(0.3 * l.tamanho * k));
  cob = { x: cob.x, w: cob.w, y: Math.max(0, ext.y0 / k - padV * 0.5), h: Math.min(p.h, ext.y1 / k + padV * 0.5) - Math.max(0, ext.y0 / k - padV * 0.5) };
  const fundo = amostrarFundo(p.canvas, emPx(cob));
  const cor = amostrarCorTexto(p.canvas, { x0: l.x * k, y0: l.y * k, x1: (l.x + l.w) * k, y1: (l.y + l.h) * k }, fundo);
  // Centralizada se as margens esquerda e direita forem iguais (±2% da largura), a linha não ocupar a página toda e
  // nenhuma outra linha começar no mesmo x (isso indicaria um bloco alinhado à esquerda). É heurística; o usuário pode trocar.
  const blocoEsquerda = (p.linhas || []).some(o => o !== l && Math.abs(o.x - l.x) < 0.01 * p.w);
  const centrada = !blocoEsquerda && Math.abs(l.x - (p.w - l.x - l.w)) < 0.02 * p.w && l.w < 0.97 * p.w;
  const a = {
    id: novoId(), pagina: i, tipo: 'edicao', linhaId: l.id, origem: l.origem,
    x: cob.x, y: cob.y, w: cob.w, h: cob.h, fundo, bx: l.x, bw: l.w, base: l.base,
    texto: l.texto, original: l.texto, tamanho: Math.round(l.tamanho * 10) / 10,
    fonte: l.fonte || 'sans', negrito: !!l.negrito, italico: !!l.italico, alinhar: centrada ? 'centro' : 'esq', cor,
  };
  const antes = JSON.stringify(estado.anotacoes);
  estado.anotacoes.push(a);
  abrirEditorTexto(i, a, { antes, novo: true });
}

// Texto que a detecção/OCR não achou: o usuário arrasta um retângulo e o app mede cor, tamanho e negrito pelos pixels.
function iniciarEdicaoManual(i, c) {
  const p = estado.paginas[i], k = p.canvas.width / p.w;
  const emPx = b => ({ x0: b.x * k, y0: b.y * k, x1: (b.x + b.w) * k, y1: (b.y + b.h) * k });
  const fundo0 = amostrarFundo(p.canvas, emPx(c));
  const ext = estenderPelaTinta(p.canvas, emPx(c), fundo0, Math.round(0.15 * c.h * k));
  const topo = Math.max(0, ext.y0 / k), fim = Math.min(p.h, ext.y1 / k);
  const cob = { x: c.x, w: c.w, y: topo, h: fim - topo };
  const fundo = amostrarFundo(p.canvas, emPx(cob));
  const med = medirTinta(p.canvas, emPx(c), fundo);
  const cor = amostrarCorTexto(p.canvas, emPx(c), fundo);
  const tam = med ? med.tamanho / k : Math.max(6, c.h / 0.9);
  const centrada = Math.abs(c.x - (p.w - c.x - c.w)) < 0.02 * p.w && c.w < 0.97 * p.w;
  const a = {
    id: novoId(), pagina: i, tipo: 'edicao', linhaId: `manual-${novoId()}`, origem: 'manual',
    x: cob.x, y: cob.y, w: cob.w, h: cob.h, fundo, bx: c.x, bw: c.w, base: med ? med.base / k : c.y + c.h * 0.82,
    texto: '', original: '', tamanho: Math.round(tam * 10) / 10,
    fonte: 'sans', negrito: !!med && med.traco > 0.115, italico: false, alinhar: centrada ? 'centro' : 'esq', cor,
  };
  const antes = JSON.stringify(estado.anotacoes);
  estado.anotacoes.push(a);
  abrirEditorTexto(i, a, { antes, novo: true });
}

// ---------- OCR sob demanda ----------
function atualizarCartaoOcr(i) {
  const p = estado.paginas[i];
  let c = p.el.querySelector('.ocr-cartao');
  const mostrar = estado.ferramenta === 'editartexto' && (p.ocrAtivo || p.ocrFeito || (p.linhasPdf && !p.linhasPdf.length));
  if (!mostrar) { c?.remove(); return; }
  const est = p.ocrAtivo ? 'rodando' : p.ocrFeito ? 'pronto' : 'oferta';
  if (c && c.dataset.estado === est) return;
  if (!c) { c = document.createElement('div'); c.className = 'ocr-cartao'; p.el.append(c); }
  c.dataset.estado = est;
  c.replaceChildren();
  const txt = (tag, t) => Object.assign(document.createElement(tag), { textContent: t });
  if (est === 'oferta') {
    const b = Object.assign(txt('button', 'Reconhecer texto desta página'), { className: 'botao primario pequeno', id: `ocr-pagina-${i + 1}` });
    b.addEventListener('click', () => executarOcr(i));
    c.append(txt('strong', 'Esta página não tem texto selecionável.'), txt('span', ' É uma imagem. O reconhecimento (OCR) roda só neste navegador, leva de alguns segundos a um minuto e pode errar: revise o texto reconhecido.'), b);
  } else if (est === 'rodando') {
    p.ocrUI = { barra: Object.assign(document.createElement('progress'), { max: 1, value: 0 }), rotulo: txt('span', 'Preparando…') };
    p.ocrUI.barra.setAttribute('aria-label', 'Andamento do OCR');
    c.append(txt('strong', 'Reconhecendo texto (OCR)'), p.ocrUI.barra, p.ocrUI.rotulo);
  } else {
    const n = (p.linhasOcr || []).length;
    c.append(txt('strong', `OCR: ${n} linha${n === 1 ? '' : 's'} reconhecida${n === 1 ? '' : 's'}.`), txt('span', ' O OCR pode errar (acentos, letras parecidas) e falha com fontes decorativas ou fundos de foto: confira o texto ao editar. Se faltar uma linha, arraste um retângulo sobre ela.'));
  }
}

async function executarOcr(i = paginaVisivel()) {
  const p = estado.paginas[i];
  if (!p || p.ocrAtivo) return;
  p.ocrAtivo = true; atualizarCartaoOcr(i);
  let canvas;
  try {
    await garantirLinhas(i);
    const pg = await estado.doc.getPage(i + 1);
    const escala = Math.max(1, Math.min(4, 2200 / p.w)); // ~2200 px de largura: bom para texto de cartaz e de documento
    const vp = pg.getViewport({ scale: escala });
    canvas = Object.assign(document.createElement('canvas'), { width: Math.floor(vp.width), height: Math.floor(vp.height) });
    await pg.render({ canvasContext: canvas.getContext('2d', { willReadFrequently: true }), canvas, viewport: vp }).promise;
    const achadas = await reconhecerCanvas(canvas, (f, rotulo) => {
      if (p.ocrUI) { p.ocrUI.barra.value = f; p.ocrUI.rotulo.textContent = `${Math.round(f * 100)}% · ${rotulo}`; }
    });
    p.linhasOcr = linhasDoOcr(achadas, canvas, canvas.width / p.w);
    p.linhas = mesclarLinhas(p.linhasPdf || [], p.linhasOcr);
    p.ocrFeito = true;
    avisar(p.linhasOcr.length ? `OCR concluído: ${p.linhasOcr.length} linha(s). Pode haver erros: revise o texto.` : 'O OCR não encontrou texto nesta página.', !p.linhasOcr.length);
  } catch (e) {
    console.warn('OCR falhou:', e);
    avisar(`Não foi possível reconhecer o texto: ${e?.message || e}`, true);
  } finally {
    p.ocrAtivo = false;
    if (canvas) canvas.width = canvas.height = 0;
    desenharAnotacoes();
  }
}

// ---------- Editor de texto no lugar ----------
// Textarea HTML transparente sobre a própria página, com a mesma fonte/tamanho/cor do resultado final (WYSIWYG).
// Enter confirma, Shift+Enter quebra linha, Esc cancela; arrastar a borda tracejada ou a alça move o texto.
const MARGEM_EDITOR = 6;

function novoTexto(i, x, y) {
  const t = tamanho(i);
  return { id: novoId(), pagina: i, tipo: 'texto', x, y: y - t * 0.6, texto: '', ...propsTexto(i) };
}

function propsTexto(i) {
  return {
    tamanho: tamanho(i), cor: cor(), fonte: $('#pFonte').value, alinhar: $('#pAlinhar').value,
    negrito: $('#pNegrito').getAttribute('aria-pressed') === 'true', italico: $('#pItalico').getAttribute('aria-pressed') === 'true',
  };
}

function abrirEditorTexto(i, a, op = {}) {
  estado.editor?.confirmar();
  const p = estado.paginas[i];
  const antes = op.antes ?? JSON.stringify(estado.anotacoes);
  estado.selecionada = null;

  const caixa = document.createElement('div');
  caixa.className = 'editor-caixa';
  const alca = Object.assign(document.createElement('span'), { className: 'editor-alca', title: 'Arraste para mover o texto' });
  const ta = document.createElement('textarea');
  ta.className = 'editor-texto';
  ta.setAttribute('aria-label', 'Texto da anotação');
  ta.setAttribute('wrap', 'off'); ta.spellcheck = false; ta.rows = 1;
  ta.value = a.texto ?? '';
  caixa.append(alca, ta);
  p.el.append(caixa);

  const ed = { a, i, ta, caixa, largura: 0 };
  ed.restilizar = () => {
    const k = p.el.clientWidth / p.w, tam = a.tamanho;
    Object.assign(ta.style, {
      fontFamily: familiaCss(a.fonte || 'helvetica'), fontWeight: a.negrito ? 700 : 400, fontStyle: a.italico ? 'italic' : 'normal',
      fontSize: `${tam * k}px`, lineHeight: `${LINHA * tam * k}px`, color: a.cor, width: '0px',
      textAlign: a.alinhar === 'centro' ? 'center' : a.alinhar === 'dir' ? 'right' : 'left',
    });
    const linhas = Math.max(1, ta.value.split('\n').length);
    ed.largura = (ta.scrollWidth + 2) / k;                      // largura do conteúdo, em pontos
    const util = larguraUtil(a) ?? ed.largura, tw = Math.max(util, ed.largura), L = esquerdaDoTexto(a);
    const esq = a.alinhar === 'centro' ? L + (util - tw) / 2 : a.alinhar === 'dir' ? L + util - tw : L;
    const topo = baseDoTexto(a) - fracaoBase(a.fonte || 'helvetica', a.negrito, a.italico) * tam;
    ed.esq = esq; ed.tw = tw; ed.util = util;
    ta.style.width = `${tw * k}px`; ta.style.height = `${linhas * LINHA * tam * k}px`;
    Object.assign(caixa.style, { left: `${esq * k - MARGEM_EDITOR}px`, top: `${topo * k - MARGEM_EDITOR}px` });
  };
  ed.cor = () => a.cor;
  sincronizarPropriedades(a);
  ed.restilizar();
  estado.editor = ed;
  desenharAnotacoes(); // esconde o texto antigo da anotação enquanto o editor o mostra
  setTimeout(() => { ta.focus(); if (op.novo) ta.select(); }, 0);
  document.fonts?.ready.then(() => estado.editor === ed && ed.restilizar());

  let feito = false;
  ed.confirmar = (cancelar = false) => {
    if (feito) return; feito = true;
    estado.editor = null;
    const texto = ta.value.replace(/\s+$/, '');
    caixa.remove();
    if (cancelar) { estado.anotacoes = JSON.parse(antes); estado.selecionada = null; desenharAnotacoes(); return; }
    a.texto = texto;
    // Texto novo mais largo que a página: reduz o tamanho até caber (com 2% de folga) e avisa.
    if (texto && (a.tipo === 'texto' || a.tipo === 'edicao') && (ed.esq < -1 || ed.esq + ed.tw > p.w + 1)) {
      const folga = 0.02 * p.w, L = esquerdaDoTexto(a), c = L + ed.util / 2;
      const livre = a.alinhar === 'centro' ? 2 * Math.min(c, p.w - c) - 2 * folga : a.alinhar === 'dir' ? L + ed.util - folga : p.w - L - folga;
      if (livre > 20) {
        a.tamanho = Math.max(4, Math.floor(a.tamanho * livre / ed.largura * 10) / 10);
        sincronizarPropriedades(a);
        setTimeout(() => avisar(`O texto passava da largura da página: o tamanho foi reduzido para ${a.tamanho} pt.`), 0);
      }
    }
    if (a.tipo === 'texto') {
      if (!texto) estado.anotacoes = estado.anotacoes.filter(z => z !== a);
      else { a.w = Math.round(ed.largura * 10) / 10; if (!estado.anotacoes.includes(a)) estado.anotacoes.push(a); }
    } else if (a.tipo === 'edicao' && op.novo && texto === a.original) {
      estado.anotacoes = estado.anotacoes.filter(z => z !== a); // aberta e fechada sem mudar nada: não cria edição
    }
    if (JSON.stringify(estado.anotacoes) !== antes) { estado.historico.push(antes); if (estado.historico.length > 60) estado.historico.shift(); salvarDepois(); }
    desenharAnotacoes();
  };

  ta.addEventListener('input', () => ed.restilizar());
  ta.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); ed.confirmar(); }
    if (ev.key === 'Escape') { ev.preventDefault(); ed.confirmar(true); }
    ev.stopPropagation();
  });
  // Sair do campo confirma, exceto ao mexer nos controles de fonte/cor/tamanho da barra (eles ajustam este mesmo texto).
  ta.addEventListener('blur', ev => { if (!ev.relatedTarget?.closest?.('[data-prop]')) ed.confirmar(); });

  // Mover: arrastar a alça ou a borda tracejada.
  let arraste = null;
  caixa.addEventListener('mousedown', ev => { if (ev.target !== ta) ev.preventDefault(); }); // mantém o foco no texto
  caixa.addEventListener('pointerdown', ev => {
    if (ev.target === ta || ev.button !== 0) return;
    ev.preventDefault(); ev.stopPropagation();
    caixa.setPointerCapture(ev.pointerId);
    arraste = { x: ev.clientX, y: ev.clientY };
    caixa.classList.add('movendo');
  });
  caixa.addEventListener('pointermove', ev => {
    if (!arraste) return;
    const k = p.el.clientWidth / p.w;
    a.tx = (a.tx || 0) + (ev.clientX - arraste.x) / k; a.ty = (a.ty || 0) + (ev.clientY - arraste.y) / k;
    arraste = { x: ev.clientX, y: ev.clientY };
    ed.restilizar();
  });
  const soltar = () => { arraste = null; caixa.classList.remove('movendo'); ta.focus(); };
  caixa.addEventListener('pointerup', soltar);
  caixa.addEventListener('pointercancel', soltar);
  return ed;
}

// ---------- Ferramentas e propriedades ----------
const cor = () => $('#pCor').value;
const COR_PADRAO = '#d0312d', COR_TEXTO_PADRAO = '#000000';
const FERRAMENTAS_TEXTO = new Set(['texto', 'cobrir', 'editartexto']);
let corEscolhida = false, tamanhoEscolhido = false; // o usuário mexeu? então não sobrescrevemos o valor
const corDestaque = () => (cor().toLowerCase() === COR_PADRAO ? '#ffe14d' : cor());
const espessura = () => Number($('#pEspessura').value);
// Tamanho do texto novo: o escolhido pelo usuário ou, por padrão, proporcional à largura da página.
function tamanho(i = paginaVisivel()) {
  if (!tamanhoEscolhido && estado.paginas[i]) $('#pTamanho').value = tamanhoPadrao(estado.paginas[i].w);
  return Number($('#pTamanho').value) || 16;
}

function escolherFerramenta(f) {
  estado.editor?.confirmar();
  estado.ferramenta = f;
  $$('.ferr[data-ferr]').forEach(b => b.classList.toggle('ativa', b.dataset.ferr === f));
  estado.paginas.forEach(p => { p.svg.dataset.ferr = f; p.hoverId = null; });
  // Texto nasce preto; as demais ferramentas mantêm o vermelho padrão — até o usuário escolher uma cor.
  if (!corEscolhida) $('#pCor').value = FERRAMENTAS_TEXTO.has(f) ? COR_TEXTO_PADRAO : COR_PADRAO;
  $('#grupoOcr').hidden = f !== 'editartexto';
  document.body.dataset.grupo = FERRAMENTAS_TEXTO.has(f) ? 'texto' : f === 'selecionar' ? 'todos' : 'forma';
  if (f !== 'selecionar' && estado.selecionada) estado.selecionada = null;
  if (f === 'editartexto' && estado.doc) {
    Promise.all(estado.paginas.map((_, i) => garantirLinhas(i))).then(() => { if (estado.ferramenta === 'editartexto') desenharAnotacoes(); });
  }
  desenharAnotacoes();
}

function sincronizarPropriedades(a) {
  if (a.cor && /^#[0-9a-f]{6}$/i.test(a.cor)) $('#pCor').value = a.cor;
  if (a.espessura) $('#pEspessura').value = a.espessura;
  if (a.tamanho) $('#pTamanho').value = Math.round(a.tamanho * 10) / 10;
  if (TIPOS_TEXTO.includes(a.tipo)) {
    $('#pFonte').value = a.fonte || 'helvetica';
    $('#pAlinhar').value = a.alinhar || 'esq';
    $('#pNegrito').setAttribute('aria-pressed', !!a.negrito);
    $('#pItalico').setAttribute('aria-pressed', !!a.italico);
  }
}

const CAMPOS_TEXTO = new Set(['fonte', 'negrito', 'italico', 'alinhar']);
function aplicarPropriedade(campo, valor) {
  if (estado.editor) { // há um texto sendo editado: a mudança vale para ele (e entra no mesmo passo do histórico)
    const ed = estado.editor;
    if (campo === 'espessura') return;
    ed.a[campo] = valor; ed.restilizar();
    if (estado.anotacoes.includes(ed.a)) desenharAnotacoes();
    ed.ta.focus();
    return;
  }
  const a = estado.anotacoes.find(z => z.id === estado.selecionada);
  if (!a || a.tipo === 'imagem') return;
  if (campo === 'tamanho' && !('tamanho' in a)) return;
  if (CAMPOS_TEXTO.has(campo) && !TIPOS_TEXTO.includes(a.tipo)) return;
  if (campo === 'espessura' && ['texto', 'destaque', 'cobrir', 'edicao'].includes(a.tipo)) return;
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
// Resolução da rasterização (opção "Remover de vez"): 3x (≈216 dpi) em páginas normais; limitada a ~4500 px no lado maior.
const escalaRaster = p => Math.max(1.5, Math.min(3, 4500 / Math.max(p.w, p.h)));

async function baixarPdfEditado() {
  estado.editor?.confirmar();
  carregando(true);
  try {
    const pgs = paginasComTextoCoberto();
    const remover = $('#removerTexto').checked && pgs.length > 0;
    const rasterizadas = new Map();
    if (remover) {
      const css = await cssFontesEmbutidas();
      for (const i of pgs) {
        rasterizadas.set(i, await paginaComoJpeg(await estado.doc.getPage(i + 1), estado.anotacoes.filter(a => a.pagina === i), estado.paginas[i], elementoAnotacao, css, escalaRaster(estado.paginas[i])));
      }
    }
    const bytes = await gerarPdfAnotado(estado.bytes, estado.paginas, estado.anotacoes, { rasterizadas });
    baixar(new Blob([bytes], { type: 'application/pdf' }), `${nomeBase()}-editado.pdf`);
    if (remover) avisar(`PDF gerado. ${pgs.length === 1 ? 'A página' : 'As páginas'} ${pgs.map(n => n + 1).join(', ')} ${pgs.length === 1 ? 'virou imagem' : 'viraram imagem'}: o texto antigo foi removido do arquivo.`);
    else if (pgs.length) avisar('PDF gerado. Atenção: o texto antigo continua dentro do arquivo e pode ser copiado.');
    else avisar('PDF editado gerado.');
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
      const url = await paginaComoPng(await estado.doc.getPage(i + 1), estado.anotacoes.filter(a => a.pagina === i), estado.paginas[i], elementoAnotacao, await cssFontesEmbutidas());
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
$('#pCor').addEventListener('input', () => { corEscolhida = true; });
$('#pCor').addEventListener('change', e => { corEscolhida = true; aplicarPropriedade('cor', e.target.value); });
$$('.cor-atalho').forEach(b => {
  b.style.background = b.dataset.cor;
  b.addEventListener('mousedown', e => e.preventDefault()); // não tira o foco do texto em edição
  b.addEventListener('click', () => { corEscolhida = true; $('#pCor').value = b.dataset.cor; aplicarPropriedade('cor', $('#pCor').value); });
});
$('#pFonte').addEventListener('change', e => aplicarPropriedade('fonte', e.target.value));
$('#pAlinhar').addEventListener('change', e => aplicarPropriedade('alinhar', e.target.value));
for (const [id, campo] of [['#pNegrito', 'negrito'], ['#pItalico', 'italico']]) {
  $(id).addEventListener('mousedown', e => e.preventDefault());
  $(id).addEventListener('click', () => { const v = $(id).getAttribute('aria-pressed') !== 'true'; $(id).setAttribute('aria-pressed', v); aplicarPropriedade(campo, v); });
}
$('#bOcr').addEventListener('click', () => executarOcr());
$('#removerTexto').addEventListener('change', atualizarAvisoRemocao);
document.fonts?.load("400 16px 'Noto Sans'"); document.fonts?.load("700 16px 'Noto Sans'"); // já deixa as fontes prontas para o editor
$('#pEspessura').addEventListener('change', e => aplicarPropriedade('espessura', Number(e.target.value)));
$('#pTamanho').addEventListener('input', () => { tamanhoEscolhido = true; });
$('#pTamanho').addEventListener('change', e => {
  const v = Math.max(4, Math.min(600, Number(e.target.value) || 16)); e.target.value = v;
  aplicarPropriedade('tamanho', v);
});
$('#bApagar').addEventListener('click', () => { estado.editor?.confirmar(); apagarSelecionada(); });
$('#bDesfazer').addEventListener('click', () => { estado.editor?.confirmar(); desfazer(); });
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

const ATALHOS = { v: 'selecionar', x: 'editartexto', t: 'texto', h: 'destaque', d: 'desenho', r: 'retangulo', e: 'elipse', l: 'linha' };
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
