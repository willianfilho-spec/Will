// Detecção de linhas de texto, amostragem de fundo/cor e utilidades de fonte para "Editar texto".

export const LINHA = 1.2, ASC = 0.8; // entrelinha e ascendente (convenção do desenho de texto, em múltiplos do tamanho)

/** Geometria do texto de uma anotação (pontos, origem no topo): borda esquerda da caixa e linha de base da 1ª linha. */
export const margemDoTexto = a => (a.tipo === 'cobrir' ? 2 : 0);
export const esquerdaDoTexto = a => (a.bx ?? (a.x + margemDoTexto(a))) + (a.tx || 0);
export const baseDoTexto = a => (a.base ?? (a.y + margemDoTexto(a) + a.tamanho * ASC)) + (a.ty || 0);
/** Largura útil da caixa para alinhar (null = sem caixa). Em 'edicao', `bx`/`bw` são a caixa da linha original (a cobertura é um pouco maior). */
export const larguraUtil = a => a.bw ?? (a.w ? a.w - 2 * margemDoTexto(a) : null);

// ---------- Fontes ----------
// 'sans' = Noto Sans embutida (OFL, vendor/fontes); as demais são as 14 fontes padrão do PDF.
export const FONTES = {
  sans: { rotulo: 'Sans (Noto Sans)', css: "'Noto Sans', 'Segoe UI', Arial, sans-serif" },
  helvetica: { rotulo: 'Helvetica', css: 'Helvetica, Arial, "Liberation Sans", sans-serif' },
  times: { rotulo: 'Times', css: '"Times New Roman", Times, "Liberation Serif", serif' },
  courier: { rotulo: 'Courier', css: '"Courier New", Courier, "Liberation Mono", monospace' },
};
export const familiaCss = f => (FONTES[f] || FONTES.helvetica).css;
export const ARQUIVOS_NOTO = {
  '400-normal': 'noto-sans-latin-400-normal.woff', '400-italic': 'noto-sans-latin-400-italic.woff',
  '700-normal': 'noto-sans-latin-700-normal.woff', '700-italic': 'noto-sans-latin-700-italic.woff',
};
export const urlFonte = chave => new URL(`./vendor/fontes/${ARQUIVOS_NOTO[chave]}`, import.meta.url).href;

/** Tamanho padrão do texto novo: proporcional à largura da página (A4 ≈ 16 pt; um cartaz de 2000 pt ≈ 53 pt). */
export const tamanhoPadrao = larguraPagina => Math.max(8, Math.round(larguraPagina / 37));

let cssFontes = null;
/** @font-face com as fontes em base64, para o SVG ser desenhado como imagem (lá fora não há acesso aos arquivos). */
export async function cssFontesEmbutidas() {
  if (cssFontes) return cssFontes;
  const partes = [];
  for (const chave of Object.keys(ARQUIVOS_NOTO)) {
    const [peso, estilo] = chave.split('-');
    const buf = new Uint8Array(await (await fetch(urlFonte(chave))).arrayBuffer());
    let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    partes.push(`@font-face{font-family:'Noto Sans';font-weight:${peso};font-style:${estilo};src:url(data:font/woff;base64,${btoa(bin)}) format('woff')}`);
  }
  return (cssFontes = partes.join(''));
}

// Posição da linha de base dentro de uma linha de texto HTML com line-height 1.2, em fração do tamanho da fonte.
const cacheBase = new Map();
export function fracaoBase(fonte, negrito, italico) {
  const chave = `${fonte}|${negrito}|${italico}`;
  if (cacheBase.has(chave)) return cacheBase.get(chave);
  const d = document.createElement('div');
  d.style.cssText = `position:absolute;visibility:hidden;left:-9999px;top:0;white-space:pre;font-size:100px;line-height:120px;font-family:${familiaCss(fonte)};font-weight:${negrito ? 700 : 400};font-style:${italico ? 'italic' : 'normal'}`;
  d.innerHTML = 'Hxg<span style="display:inline-block;width:0;height:0;vertical-align:baseline"></span>';
  document.body.append(d);
  const f = d.lastChild.offsetTop / 100;
  d.remove();
  cacheBase.set(chave, f);
  return f;
}

// ---------- Cores ----------
// Lê pixels de uma região copiando-a para um canvas auxiliar (evita a leitura repetida do canvas visível, que fica na GPU).
let auxiliar = null;
function pixels(canvas, x, y, w, h) {
  auxiliar ??= document.createElement('canvas');
  auxiliar.width = w; auxiliar.height = h;
  const ctx = auxiliar.getContext('2d', { willReadFrequently: true });
  ctx.clearRect(0, 0, w, h);
  ctx.drawImage(canvas, x, y, w, h, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h);
}

const hex = (r, g, b) => '#' + [r, g, b].map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
export function hexParaRgb(h) { const n = parseInt(String(h).slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
const mediana = arr => { if (!arr.length) return 0; arr.sort((a, b) => a - b); return arr[arr.length >> 1]; };
const luminancia = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const dist = (r, g, b, c) => Math.abs(r - c[0]) + Math.abs(g - c[1]) + Math.abs(b - c[2]);

/**
 * Cor (hex) do fundo na posição relativa (u horizontal, t vertical; 0 = esquerda/topo, 1 = direita/base).
 * `fundo` pode ser: um hex; uma lista de hex (degradê vertical, do topo à base); ou uma lista de colunas, cada uma
 * uma lista vertical (fundo que também varia na horizontal; a coluna é a mais próxima de u).
 */
export function corDoFundo(fundo, t, u = 0.5) {
  if (typeof fundo === 'string') return fundo;
  if (Array.isArray(fundo[0])) return corDoFundo(fundo[Math.max(0, Math.min(fundo.length - 1, Math.floor(u * fundo.length)))], t);
  const n = fundo.length; if (n === 1) return fundo[0];
  const pos = Math.max(0, Math.min(n - 1, t * n - 0.5)), i = Math.floor(pos), f = pos - i;
  const a = hexParaRgb(fundo[i]), b = hexParaRgb(fundo[Math.min(n - 1, i + 1)]);
  return hex(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f);
}

/**
 * Amostra o fundo AO REDOR de uma caixa (px do canvas): usa só o anel externo (3 px), nunca o interior (onde está o texto).
 * Divide a altura em faixas e toma a MEDIANA por canal em cada uma. Se as faixas quase não diferem, devolve uma cor
 * única (hex); se diferem (degradê vertical), devolve a lista de cores por faixa, do topo para a base.
 * Variação só na horizontal (ex.: foto atrás do texto) NÃO é reproduzida: ver README.
 */
export function amostrarFundo(canvas, c) {
  const W = canvas.width, H = canvas.height, m = 3;
  const x0 = Math.max(0, Math.floor(c.x0)), y0 = Math.max(0, Math.floor(c.y0));
  const x1 = Math.min(W, Math.ceil(c.x1)), y1 = Math.min(H, Math.ceil(c.y1));
  const rx0 = Math.max(0, x0 - m), ry0 = Math.max(0, y0 - m), rx1 = Math.min(W, x1 + m), ry1 = Math.min(H, y1 + m);
  if (rx1 <= rx0 || ry1 <= ry0) return '#ffffff';
  const img = pixels(canvas, rx0, ry0, rx1 - rx0, ry1 - ry0), d = img.data, lw = rx1 - rx0;
  const nB = Math.max(1, Math.min(16, Math.round((y1 - y0) / 8)));
  const medianaDe = lista => (lista.length ? [0, 1, 2].map(ch => mediana(lista.map(o => d[o + ch]))) : null);
  // Pixels do anel: faixa de cima, faixa de baixo e as duas laterais (por altura relativa dentro da caixa).
  const cima = [], baixo = [], lados = Array.from({ length: nB }, () => []);
  for (let y = ry0; y < ry1; y++) {
    const dentroY = y >= y0 && y < y1;
    for (let x = rx0; x < rx1; x++) {
      if (dentroY && x >= x0 && x < x1) continue;   // interior da caixa: é o texto, não é fundo
      const o = ((y - ry0) * lw + (x - rx0)) * 4;
      if (y < y0) cima.push(o); else if (y >= y1) baixo.push(o);
      else lados[Math.min(nB - 1, Math.floor((y - y0) / (y1 - y0) * nB))].push(o);
    }
  }
  const todos = [...cima, ...baixo, ...lados.flat()];
  if (!todos.length) return '#ffffff';
  const geral = medianaDe(todos);
  // Variação horizontal (ex.: foto atrás do texto): colunas de cima e de baixo; entre elas interpola na vertical.
  const nC = Math.max(1, Math.min(24, Math.round((x1 - x0) / 24)));
  if (nC > 2 && (cima.length || baixo.length)) {
    const colunaDe = o => Math.max(0, Math.min(nC - 1, Math.floor((rx0 + ((o / 4) % lw) - x0) / (x1 - x0) * nC)));
    const porColuna = lista => { const g = Array.from({ length: nC }, () => []); for (const o of lista) g[colunaDe(o)].push(o); return g.map(l => medianaDe(l)); };
    const preencher = cs => cs.map((c0, i) => c0 || (() => { for (let k = 1; k < nC; k++) { const v = cs[i - k] || cs[i + k]; if (v) return v; } return geral; })());
    const suavizar = cs => cs.map((_, i) => [0, 1, 2].map(ch => mediana([cs[Math.max(0, i - 1)][ch], cs[i][ch], cs[Math.min(nC - 1, i + 1)][ch]])));
    const topo = cima.length ? suavizar(preencher(porColuna(cima))) : null, fundoB = baixo.length ? suavizar(preencher(porColuna(baixo))) : null;
    const ref = topo || fundoB;
    const variacao = Math.max(...ref.map(c0 => Math.max(...c0.map((v, ch) => Math.abs(v - mediana(ref.map(r => r[ch])))))));
    if (variacao > 14) return ref.map((_, i) => [hex(...(topo || fundoB)[i]), hex(...(fundoB || topo)[i])]);
  }
  // Cima e baixo costumam estar livres de texto, enquanto as laterais podem cortar letras (retângulo desenhado no meio de
  // uma palavra). Por isso o degradê é estimado primeiro por cima/baixo; as laterais só refinam o que concordar com ele.
  const mc = medianaDe(cima), mb = medianaDe(baixo);
  const esperado = t => (mc && mb ? mc.map((v, ch) => v + (mb[ch] - v) * t) : (mc || mb));
  let cores = lados.map((lista, k) => {
    const t = (k + 0.5) / nB, ref = esperado(t);
    const aceitos = ref ? lista.filter(o => Math.abs(d[o] - ref[0]) + Math.abs(d[o + 1] - ref[1]) + Math.abs(d[o + 2] - ref[2]) <= 60) : lista;
    return aceitos.length >= 6 ? medianaDe(aceitos) : (ref || medianaDe(lista) || geral);
  });
  // mediana de 3 vizinhas: tira o ruído de uma letra vizinha que invadiu o anel
  const suave = cores.map((_, i) => [0, 1, 2].map(ch => mediana([cores[Math.max(0, i - 1)][ch], cores[i][ch], cores[Math.min(nB - 1, i + 1)][ch]])));
  const centro = nB === 1 ? suave[0] : geral;
  const desvio = Math.max(...suave.map(c0 => Math.max(...c0.map((v, ch) => Math.abs(v - centro[ch])))));
  if (nB === 1 || desvio <= 8) return hex(...(mc && mb ? mc.map((v, ch) => (v + mb[ch]) / 2) : centro).map((v, ch) => (nB === 1 ? suave[0][ch] : v)));
  return suave.map(c0 => hex(...c0));
}

/**
 * Cor do texto: média dos pixels mais distantes do fundo dentro da caixa (os ~4% mais contrastantes).
 * Se quase não há contraste, escolhe preto ou branco conforme o fundo.
 */
export function amostrarCorTexto(canvas, c, fundo) {
  const x0 = Math.max(0, Math.floor(c.x0)), y0 = Math.max(0, Math.floor(c.y0));
  const x1 = Math.min(canvas.width, Math.ceil(c.x1)), y1 = Math.min(canvas.height, Math.ceil(c.y1));
  if (x1 <= x0 || y1 <= y0) return '#000000';
  const d = pixels(canvas, x0, y0, x1 - x0, y1 - y0).data, w = x1 - x0, h = y1 - y0;
  const cores = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const bg = hexParaRgb(corDoFundo(fundo, (y + 0.5) / h, (x + 0.5) / w)), o = (y * w + x) * 4;
      cores.push([dist(d[o], d[o + 1], d[o + 2], bg), d[o], d[o + 1], d[o + 2]]);
    }
  }
  cores.sort((a, b) => b[0] - a[0]);
  if (cores[0][0] < 60) return luminancia(hexParaRgb(corDoFundo(fundo, 0.5))) > 140 ? '#000000' : '#ffffff';
  const n = Math.max(3, Math.floor(cores.length * 0.04));
  const top = cores.slice(0, n);
  return hex(mediana(top.map(t => t[1])), mediana(top.map(t => t[2])), mediana(top.map(t => t[3])));
}

/**
 * Mede o texto dentro da caixa (px do canvas) a partir dos pixels: linha de base, altura de maiúscula e espessura do traço.
 * Devolve { base, tamanho, traco } em px: `tamanho` = tamanho de fonte estimado (altura de maiúscula / 0,72),
 * `traco` = espessura mediana do traço dividida por esse tamanho (≈0,09 em fontes normais; ≥0,13 em negrito).
 */
export function medirTinta(canvas, c, fundo) {
  const x0 = Math.max(0, Math.floor(c.x0)), y0 = Math.max(0, Math.floor(c.y0));
  const x1 = Math.min(canvas.width, Math.ceil(c.x1)), y1 = Math.min(canvas.height, Math.ceil(c.y1));
  const w = x1 - x0, h = y1 - y0;
  if (w < 4 || h < 4) return null;
  const d = pixels(canvas, x0, y0, w, h).data;
  const dd = new Float32Array(w * h); let maxd = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const bg = hexParaRgb(corDoFundo(fundo, (y + 0.5) / h, (x + 0.5) / w)), o = (y * w + x) * 4, v = dist(d[o], d[o + 1], d[o + 2], bg);
      dd[y * w + x] = v; if (v > maxd) maxd = v;
    }
  }
  if (maxd < 60) return null;
  const lim = maxd * 0.5;
  const linhas = new Array(h).fill(0);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (dd[y * w + x] > lim) linhas[y]++;
  const maxL = Math.max(...linhas);
  let topo = 0; while (topo < h && linhas[topo] < maxL * 0.12) topo++;
  let base = h - 1; while (base > 0 && linhas[base] < maxL * 0.3) base--;
  base += 1;
  if (base - topo < 4) return null;
  const capH = base - topo;
  // espessura do traço: comprimentos das corridas de tinta no terço central das linhas de letra
  const corridas = [];
  for (let y = Math.round(topo + capH * 0.3); y < Math.round(topo + capH * 0.7); y++) {
    let n = 0;
    for (let x = 0; x <= w; x++) {
      if (x < w && dd[y * w + x] > lim) n++; else { if (n) corridas.push(n); n = 0; }
    }
  }
  const tamanho = capH / 0.72;
  return { base: y0 + base, topo: y0 + topo, tamanho, traco: corridas.length ? mediana(corridas) / tamanho : 0 };
}

/**
 * Estende a caixa (px) para cima e para baixo enquanto houver tinta contígua (acentos, til, cedilha, vírgula) que as
 * métricas da fonte ou o OCR deixaram de fora. Para após 2 linhas de pixels sem tinta ou em `maximo` px de extensão.
 * `fundo` é o amostrado da caixa original; fora dela o degradê é extrapolado pela faixa mais próxima.
 */
export function estenderPelaTinta(canvas, c, fundo, maximo) {
  const x0 = Math.max(0, Math.floor(c.x0)), x1 = Math.min(canvas.width, Math.ceil(c.x1));
  const y0 = Math.floor(c.y0), y1 = Math.ceil(c.y1), h0 = Math.max(1, y1 - y0);
  const topo = Math.max(0, y0 - maximo), base = Math.min(canvas.height, y1 + maximo);
  if (x1 <= x0 || base <= topo) return c;
  const w = x1 - x0, d = pixels(canvas, x0, topo, w, base - topo).data;
  const tintaNaLinha = y => {
    const t = Math.max(0, Math.min(1, (y - y0 + 0.5) / h0));
    let n = 0;
    for (let x = 0; x < w; x++) {
      const bg = hexParaRgb(corDoFundo(fundo, t, (x + 0.5) / w)), o = ((y - topo) * w + x) * 4;
      if (dist(d[o], d[o + 1], d[o + 2], bg) > 45 && ++n >= 2) return true;
    }
    return false;
  };
  let novoTopo = y0, vazias = 0;
  for (let y = y0 - 1; y >= topo; y--) { if (tintaNaLinha(y)) { novoTopo = y; vazias = 0; } else if (++vazias > 2) break; }
  let novaBase = y1, v2 = 0;
  for (let y = y1; y < base; y++) { if (tintaNaLinha(y)) { novaBase = y + 1; v2 = 0; } else if (++v2 > 2) break; }
  return { x0: c.x0, x1: c.x1, y0: novoTopo, y1: novaBase };
}

// ---------- Linhas de texto da camada de texto do PDF ----------
const aplicar = (t, x, y) => [t[0] * x + t[2] * y + t[4], t[1] * x + t[3] * y + t[5]];

function infoFonte(page, styles, nomeFonte) {
  let f = null;
  try { f = page.commonObjs.get(nomeFonte); } catch { /* fonte ainda não carregada */ }
  const nome = String(f?.name || f?.loadedName || styles?.[nomeFonte]?.fontFamily || '');
  const fam = String(styles?.[nomeFonte]?.fontFamily || '').toLowerCase();
  const negrito = !!(f?.bold || f?.black) || /bold|black|heavy|demi|semibold/i.test(nome);
  const italico = !!f?.italic || /italic|oblique/i.test(nome);
  // Casa com a fonte padrão do PDF quando for a mesma família (métricas idênticas); senão cai em Noto Sans (ou Times se serifada).
  const fonte = /courier|consolas|monaco|lucida console|mono/i.test(nome) || /mono/.test(fam) ? 'courier'
    : /helvetica|arial|liberation ?sans|nimbus ?sans/i.test(nome) ? 'helvetica'
    : /times|liberation ?serif|nimbus ?roman/i.test(nome) ? 'times'
    : (/serif/.test(fam) && !/sans/.test(fam)) || /georgia|garamond|palatino|cambria|book/i.test(nome) ? 'times' : 'sans';
  return { nome, negrito, italico, fonte };
}

/**
 * Agrupa os itens de getTextContent() em linhas (mesma linha de base, lacuna horizontal pequena).
 * `transform` é o do viewport em escala 1 do pdf.js (já considera /Rotate e CropBox).
 * Coordenadas devolvidas em pontos, origem no canto superior esquerdo da página exibida.
 * Linhas inclinadas (mais de 4°) são ignoradas.
 */
export async function linhasDoPdf(page, transform) {
  const tc = await page.getTextContent();
  const itens = [];
  for (const it of tc.items) {
    if (!('str' in it) || !it.str) continue;
    const [a, b, c, dd, e, f] = it.transform;
    const fs = Math.hypot(c, dd), ln = Math.hypot(a, b);
    if (!fs || !ln) continue;
    const u = [a / ln, b / ln], v = [-u[1], u[0]];
    const p0 = [e, f], p1 = [e + u[0] * it.width, f + u[1] * it.width];
    const [X0, Y0] = aplicar(transform, ...p0), [X1, Y1] = aplicar(transform, ...p1);
    const ang = Math.atan2(Y1 - Y0, X1 - X0) * 180 / Math.PI;
    if (Math.abs(ang) > 4) continue;
    const [, Yup] = aplicar(transform, e + v[0] * fs, f + v[1] * fs);
    const tam = Math.abs(Y0 - Yup);
    if (!/\S/.test(it.str)) { itens.push({ str: it.str, x0: Math.min(X0, X1), x1: Math.max(X0, X1), base: Y0, tam, vazio: true }); continue; }
    itens.push({ str: it.str, x0: Math.min(X0, X1), x1: Math.max(X0, X1), base: Y0, tam, ...infoFonte(page, tc.styles, it.fontName) });
  }
  const linhas = [];
  for (const it of itens) {
    let alvo = null;
    for (let k = linhas.length - 1; k >= 0 && k > linhas.length - 40; k--) {
      const l = linhas[k];
      if (Math.abs(l.base - it.base) < 0.35 * Math.min(l.tam, it.tam || l.tam) && it.x0 - l.x1 > -0.6 * l.tam && it.x0 - l.x1 < 1.3 * l.tam) { alvo = l; break; }
    }
    if (!alvo) { if (it.vazio) continue; alvo = { base: it.base, tam: it.tam, x0: it.x0, x1: it.x1, itens: [] }; linhas.push(alvo); }
    alvo.itens.push(it); alvo.x0 = Math.min(alvo.x0, it.x0); alvo.x1 = Math.max(alvo.x1, it.x1);
  }
  const saida = [];
  for (const l of linhas) {
    l.itens.sort((p, q) => p.x0 - q.x0);
    let texto = '', fim = null;
    for (const it of l.itens) {
      if (fim !== null && it.x0 - fim > 0.18 * l.tam && !/\s$/.test(texto) && !/^\s/.test(it.str)) texto += ' ';
      texto += it.str; fim = it.x1;
    }
    texto = texto.replace(/\s+/g, ' ').trim();
    if (!texto) continue;
    const ref = l.itens.filter(i => !i.vazio).sort((p, q) => q.str.length - p.str.length)[0];
    const tam = Math.max(...l.itens.filter(i => !i.vazio).map(i => i.tam));
    saida.push({
      id: `pdf-${saida.length}`, origem: 'pdf', texto, base: l.base, tamanho: tam,
      x: l.x0, w: l.x1 - l.x0, y: l.base - 0.85 * tam, h: 1.06 * tam,
      negrito: ref.negrito, italico: ref.italico, fonte: ref.fonte, fonteNome: ref.nome,
    });
  }
  return saida.sort((p, q) => p.y - q.y || p.x - q.x);
}

/** Converte as linhas do OCR (px do canvas de OCR) em linhas em pontos e mede cor/tamanho/negrito nos pixels. */
export function linhasDoOcr(linhasOcr, canvas, px) {
  const saida = [];
  for (const l of linhasOcr) {
    // Em fundo de foto/ruído o OCR inventa "linhas" de lixo: descarta confiança baixa ou pouco texto de verdade.
    const util = (l.texto.match(/[\p{L}\p{N}]/gu) || []).length;
    if (l.confianca < 50 || util < 2 || util / l.texto.replace(/\s/g, '').length < 0.6) continue;
    const cx = { x0: l.caixa.x0, y0: l.caixa.y0, x1: l.caixa.x1, y1: l.caixa.y1 };
    const pad = Math.max(2, (cx.y1 - cx.y0) * 0.1);
    const fundo = amostrarFundo(canvas, { x0: cx.x0 - pad, y0: cx.y0 - pad, x1: cx.x1 + pad, y1: cx.y1 + pad });
    const med = medirTinta(canvas, cx, fundo);
    const baseY = med ? med.base : cx.y1 - (cx.y1 - cx.y0) * 0.2;
    const tamPx = med ? med.tamanho : (cx.y1 - cx.y0) / 0.9;
    saida.push({
      id: `ocr-${saida.length}`, origem: 'ocr', texto: l.texto, confianca: l.confianca,
      base: baseY / px, tamanho: tamPx / px,
      x: cx.x0 / px, w: (cx.x1 - cx.x0) / px, y: cx.y0 / px, h: (cx.y1 - cx.y0) / px,
      negrito: !!med && med.traco > 0.115, italico: false, fonte: 'sans', fonteNome: '',
      tracoMedido: med?.traco ?? null,
    });
  }
  return saida;
}

/** Descarta linhas de OCR que repetem texto já existente na camada de texto (sobreposição > 50% da área menor). */
export function mesclarLinhas(pdf, ocr) {
  const inter = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const novas = ocr.filter(o => !pdf.some(p => inter(o, p) > 0.5 * Math.min(o.w * o.h, p.w * p.h)));
  return [...pdf, ...novas].sort((p, q) => p.y - q.y || p.x - q.x);
}
