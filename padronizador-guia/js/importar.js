// Importação de PDF e PPTX para a estrutura do guia.
// 1) extrai "segmentos" de texto (posição, tamanho, negrito), imagens e tabelas;
// 2) o classificador reconhece os componentes do modelo e monta os blocos.
// É heurístico: o resultado sempre passa pela revisão do usuário no editor.
import * as pdfjs from '../../editor-pdf/vendor/pdfjs/pdf.min.mjs';
import { abrirZip } from './zip.js';
import { A4, SECOES, sem, blocoVazio } from './layout.js';

const VENDOR = new URL('../../editor-pdf/vendor/pdfjs/', import.meta.url).href;
pdfjs.GlobalWorkerOptions.workerSrc = VENDOR + 'pdf.worker.min.mjs';

// ================================================================ PDF
export async function importarPdf(buffer, progresso = () => {}) {
  const tarefa = pdfjs.getDocument({ data: new Uint8Array(buffer), standardFontDataUrl: VENDOR + 'standard_fonts/', cMapUrl: VENDOR + 'cmaps/', cMapPacked: true, wasmUrl: VENDOR + 'wasm/', fontExtraProperties: true });
  const pdf = await tarefa.promise;
  const paginas = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    progresso(n, pdf.numPages);
    const page = await pdf.getPage(n);
    const vp1 = page.getViewport({ scale: 1 });
    const s = A4.w / vp1.width;
    const vp = page.getViewport({ scale: s });       // em pontos A4
    const ops = await page.getOperatorList();
    const tc = await page.getTextContent();

    const segs = [];
    for (const it of tc.items) {
      if (!it.str || !it.str.trim()) continue;
      const tr = pdfjs.Util.transform(vp.transform, it.transform);
      const size = Math.hypot(tr[2], tr[3]) || 10;
      let bold = false;
      try {
        const f = page.commonObjs.get(it.fontName);
        bold = !!(f?.bold || f?.black) || /bold|black|heavy|semibold|-bd\b/i.test(f?.name || '');
      } catch { /* fonte não resolvida */ }
      segs.push({ t: it.str.replace(/\s+/g, ' ').trim(), x: tr[4], y: tr[5] - size * 0.8, w: it.width * s, size, bold });
    }

    // Caixas das imagens, acompanhando a matriz de transformação do operator list.
    const caixas = [];
    let ctm = [1, 0, 0, 1, 0, 0]; const pilha = [];
    const O = pdfjs.OPS;
    for (let i = 0; i < ops.fnArray.length; i++) {
      const fn = ops.fnArray[i], a = ops.argsArray[i];
      if (fn === O.save) pilha.push(ctm.slice());
      else if (fn === O.restore) ctm = pilha.pop() || ctm;
      else if (fn === O.transform) ctm = pdfjs.Util.transform(ctm, a);
      else if (fn === O.paintFormXObjectBegin) { pilha.push(ctm.slice()); if (Array.isArray(a?.[0]) && a[0].length === 6) ctm = pdfjs.Util.transform(ctm, a[0]); }
      else if (fn === O.paintFormXObjectEnd) ctm = pilha.pop() || ctm;
      else if (fn === O.paintImageXObject || fn === O.paintInlineImageXObject || fn === O.paintImageXObjectRepeat) {
        const m = pdfjs.Util.transform(vp.transform, ctm);
        const pts = [[0, 0], [1, 0], [0, 1], [1, 1]].map(([u, v]) => [m[0] * u + m[2] * v + m[4], m[1] * u + m[3] * v + m[5]]);
        const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
        const x0 = Math.max(0, Math.min(...xs)), y0 = Math.max(0, Math.min(...ys));
        const x1 = Math.min(A4.w, Math.max(...xs)), y1 = Math.min(A4.h, Math.max(...ys));
        if (x1 - x0 > 25 && y1 - y0 > 18) caixas.push({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
      }
    }

    // Renderiza a página (2x) para recortar as imagens e guardar a versão original.
    const esc = 2;
    const cv = document.createElement('canvas');
    cv.width = Math.round(A4.w * esc); cv.height = Math.round(vp.height * esc);
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
    await page.render({ canvasContext: ctx, viewport: page.getViewport({ scale: s * esc }) }).promise;

    const imgs = [];
    for (const b of caixas) {
      const ehLogo = b.y < 90 && b.x > A4.w * 0.7 && b.w < 110;
      const fundo = b.w > A4.w * 0.95 && b.h > vp.height * 0.9;
      if (ehLogo || fundo) continue;
      if (imgs.some((o) => Math.abs(o.x - b.x) < 3 && Math.abs(o.y - b.y) < 3 && Math.abs(o.w - b.w) < 3)) continue;
      const c2 = document.createElement('canvas');
      c2.width = Math.round(b.w * esc); c2.height = Math.round(b.h * esc);
      const x2 = c2.getContext('2d', { willReadFrequently: true });
      x2.drawImage(cv, b.x * esc, b.y * esc, b.w * esc, b.h * esc, 0, 0, c2.width, c2.height);
      if (uniforme(x2, c2.width, c2.height)) continue;
      imgs.push({ ...b, src: c2.toDataURL('image/jpeg', 0.9), iw: c2.width, ih: c2.height });
    }
    const c3 = document.createElement('canvas');
    c3.width = Math.round(A4.w * 1.5); c3.height = Math.round(A4.h * 1.5);
    const x3 = c3.getContext('2d'); x3.fillStyle = '#fff'; x3.fillRect(0, 0, c3.width, c3.height);
    x3.drawImage(cv, 0, 0, c3.width, c3.height);
    const original = c3.toDataURL('image/jpeg', 0.82);
    page.cleanup();

    paginas.push(classificar({ segs, imgs, tabs: [] }, n - 1, pdf.numPages, original));
  }
  await tarefa.destroy();
  return paginas;
}

// Recorte praticamente de uma cor só (máscara, fundo branco): não é conteúdo.
function uniforme(ctx, w, h) {
  const d = ctx.getImageData(0, 0, w, h).data;
  const passo = Math.max(4, Math.floor(d.length / 4 / 4000)) * 4;
  let n = 0, s = 0, s2 = 0;
  for (let i = 0; i < d.length; i += passo) { const v = (d[i] + d[i + 1] + d[i + 2]) / 3; s += v; s2 += v * v; n++; }
  const media = s / n;
  return Math.sqrt(Math.max(0, s2 / n - media * media)) < 4;
}

// ================================================================ PPTX
const filhos = (el, nome) => (el ? [...el.children].filter((c) => c.localName === nome) : []);
const filho = (el, nome) => filhos(el, nome)[0];
const desc = (el, nome) => (el ? [...el.getElementsByTagName('*')].filter((c) => c.localName === nome) : []);
const attrR = (el, nome) => el?.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', nome) || el?.getAttribute('r:' + nome);

function resolver(base, alvo) {
  if (alvo.startsWith('/')) return alvo.slice(1);
  const p = base.split('/'); p.pop();
  for (const parte of alvo.split('/')) { if (parte === '..') p.pop(); else if (parte !== '.') p.push(parte); }
  return p.join('/');
}

async function lerRels(zip, caminho) {
  const pasta = caminho.split('/'); const arq = pasta.pop();
  const xml = await zip.texto(pasta.join('/') + '/_rels/' + arq + '.rels');
  const m = new Map();
  if (!xml) return m;
  const d = new DOMParser().parseFromString(xml, 'application/xml');
  for (const r of desc(d.documentElement, 'Relationship')) m.set(r.getAttribute('Id'), resolver(caminho, r.getAttribute('Target')));
  return m;
}

const MIME = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp', webp: 'image/webp', svg: 'image/svg+xml' };

async function paraDataUrlCompativel(bytes, mime) {
  // pdf-lib só embute PNG e JPEG: o resto é convertido para PNG via canvas.
  const blob = new Blob([bytes], { type: mime });
  const bmp = await createImageBitmap(blob);
  const cv = document.createElement('canvas'); cv.width = bmp.width; cv.height = bmp.height;
  cv.getContext('2d').drawImage(bmp, 0, 0);
  const jpeg = mime === 'image/jpeg';
  const src = jpeg ? await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(blob); }) : cv.toDataURL('image/png');
  return { src, iw: bmp.width, ih: bmp.height };
}

export async function importarPptx(buffer, progresso = () => {}) {
  const zip = await abrirZip(buffer);
  const parse = async (n) => { const x = await zip.texto(n); return x ? new DOMParser().parseFromString(x, 'application/xml') : null; };
  const pres = await parse('ppt/presentation.xml');
  if (!pres) throw new Error('PPTX sem ppt/presentation.xml.');
  const sz = desc(pres.documentElement, 'sldSz')[0];
  const cx = +(sz?.getAttribute('cx') || 9144000);
  const E = A4.w / cx;                                   // EMU → pontos A4 (escala uniforme)
  const rels = await lerRels(zip, 'ppt/presentation.xml');
  const ids = desc(pres.documentElement, 'sldId').map((s) => rels.get(attrR(s, 'id'))).filter(Boolean);
  const paginas = [];
  for (let n = 0; n < ids.length; n++) {
    progresso(n + 1, ids.length);
    const caminho = ids[n];
    const doc = await parse(caminho);
    const srels = await lerRels(zip, caminho);
    const segs = [], imgs = [], tabs = [], avisos = [];
    let ordem = 0;

    const xfrmDe = (el) => {
      const x = filho(el, 'xfrm');
      const off = filho(x, 'off'), ext = filho(x, 'ext');
      if (!off || !ext) return null;
      return { x: +off.getAttribute('x'), y: +off.getAttribute('y'), w: +ext.getAttribute('cx'), h: +ext.getAttribute('cy'), x2: x };
    };
    const aplicar = (tf, b) => ({ x: tf.ox + (b.x - tf.cox) * tf.sx, y: tf.oy + (b.y - tf.coy) * tf.sy, w: b.w * tf.sx, h: b.h * tf.sy });

    const textoDoCorpo = (corpo, caixa, ph) => {
      let y = caixa.y * E + 4;
      let numAuto = 0;
      for (const p of filhos(corpo, 'p')) {
        const runs = [...filhos(p, 'r'), ...filhos(p, 'fld')];
        let t = '';
        for (const ch of p.children) {
          if (ch.localName === 'r' || ch.localName === 'fld') t += filho(ch, 't')?.textContent || '';
          else if (ch.localName === 'br') t += '\n';
        }
        const ppr = filho(p, 'pPr');
        const rpr = runs.map((r) => filho(r, 'rPr')).filter(Boolean);
        const size = (+(rpr.find((r) => r.getAttribute('sz'))?.getAttribute('sz')) || 1800) / 100 * (E * 12700);
        if (!t.trim()) { y += size * 0.9; continue; }
        const bold = rpr.length > 0 && rpr.filter((r) => r.getAttribute('b') === '1').length >= rpr.length / 2;
        if (filho(ppr, 'buChar')) t = '• ' + t;
        else if (filho(ppr, 'buAutoNum')) t = `${++numAuto}. ` + t;
        const w = caixa.w * E;
        for (const linha of t.split('\n')) {
          if (!linha.trim()) continue;
          const estW = Math.min(w, linha.length * size * 0.5);
          segs.push({ t: linha.trim(), x: caixa.x * E + 7, y, w: estW, size, bold: bold || ph === 'title' || ph === 'ctrTitle', ordem: ordem++ });
          y += Math.max(1, Math.ceil((linha.length * size * 0.5) / Math.max(40, w - 14))) * size * 1.2;
        }
      }
    };

    const visitar = async (no, tf) => {
      for (const el of no.children) {
        const nome = el.localName;
        if (nome === 'sp') {
          const spPr = filho(el, 'spPr');
          const ph = desc(filho(el, 'nvSpPr'), 'ph')[0]?.getAttribute('type') || '';
          const b = xfrmDe(spPr);
          const caixa = b ? aplicar(tf, b) : { x: 0, y: ordem * 2000, w: cx, h: 0 };
          const corpo = filho(el, 'txBody');
          if (corpo) textoDoCorpo(corpo, caixa, ph);
        } else if (nome === 'pic') {
          const b = xfrmDe(filho(el, 'spPr'));
          const blip = desc(el, 'blip')[0];
          const alvo = srels.get(attrR(blip, 'embed'));
          if (!b || !alvo) continue;
          const ext = alvo.split('.').pop().toLowerCase();
          const mime = MIME[ext];
          if (!mime) { avisos.push(`Imagem em formato ${ext.toUpperCase()} não suportado pelo navegador: ${alvo.split('/').pop()}.`); continue; }
          try {
            const bytes = await zip.bytes(alvo);
            const im = await paraDataUrlCompativel(bytes, mime);
            const c = aplicar(tf, b);
            imgs.push({ x: c.x * E, y: c.y * E, w: c.w * E, h: c.h * E, ...im });
          } catch { avisos.push(`Não foi possível ler a imagem ${alvo.split('/').pop()}.`); }
        } else if (nome === 'grpSp') {
          const g = filho(filho(el, 'grpSpPr'), 'xfrm');
          const off = filho(g, 'off'), ext = filho(g, 'ext'), co = filho(g, 'chOff'), ce = filho(g, 'chExt');
          let tf2 = tf;
          if (off && ext && co && ce) {
            const b = aplicar(tf, { x: +off.getAttribute('x'), y: +off.getAttribute('y'), w: +ext.getAttribute('cx'), h: +ext.getAttribute('cy') });
            const cw = +ce.getAttribute('cx') || 1, ch = +ce.getAttribute('cy') || 1;
            tf2 = { ox: b.x, oy: b.y, cox: +co.getAttribute('x'), coy: +co.getAttribute('y'), sx: b.w / cw, sy: b.h / ch };
          }
          await visitar(el, tf2);
        } else if (nome === 'graphicFrame') {
          const tbl = desc(el, 'tbl')[0];
          const b = xfrmDe(el);
          if (!tbl || !b) continue;
          const c = aplicar(tf, b);
          const linhas = filhos(tbl, 'tr').map((tr) => filhos(tr, 'tc').map((tc) => desc(tc, 'p').map((p) => desc(p, 't').map((t) => t.textContent).join('')).filter(Boolean).join('\n')));
          tabs.push({ x: c.x * E, y: c.y * E, w: c.w * E, h: c.h * E, linhas });
        }
      }
    };
    const arvore = desc(doc.documentElement, 'spTree')[0];
    if (arvore) await visitar(arvore, { ox: 0, oy: 0, cox: 0, coy: 0, sx: 1, sy: 1 });
    const pg = classificar({ segs, imgs, tabs }, n, ids.length, null);
    pg.avisos.push(...avisos);
    paginas.push(pg);
  }
  return paginas;
}

// ================================================================ classificador
const ROTULOS = [
  [/^CAMINHO NO SIGAA/, 'caminho'],
  [/^(COMO FAZER|PASSO A PASSO|PASSOS|PROCEDIMENTOS?)\b/, 'passos'],
  [/^TELAS? DO SIGAA/, 'imagem'],
  [/^(OBSERVACAO|OBSERVACOES|NOTA|DICA)\b/, 'observacao'],
  [/^(REGULAMENTACAO|NORMATIVOS?( RELACIONADOS)?|BASE LEGAL|LEGISLACAO)\b/, 'regulamentacao'],
  [/^(ATENCAO|IMPORTANTE|CUIDADO)\b/, 'atencao'],
  [/^APRESENTACAO\b/, 'destaque'],
  [/^(QUANDO USAR|TIPOS DE [A-Z]+|FLUXO D[AOE] [A-Z ]+|DEFINICAO|OBJETIVO|RESULTADO [A-Z ]+|COMO USAR [A-Z ]+)/, 'texto'],
];
const NUM = /^\d{1,2}$/;
const ehFonte = (t) => /^fonte\s*:/i.test(t);

function rotuloDe(seg) {
  const n = sem(seg.t).replace(/[:.]+$/, '');
  for (const [re, tipo] of ROTULOS) {
    const m = n.match(re);
    if (m && (seg.bold || n === m[0]) && m[0].length >= n.length - 60) return { tipo, txt: m[0], resto: seg.t.slice(m[0].length).replace(/^[\s:–-]+/, '') };
  }
  return null;
}

// Junta pedaços vizinhos na mesma linha (pdf.js e PPTX costumam fatiar o texto).
function emLinhas(segs) {
  const ord = [...segs].sort((a, b) => a.y - b.y || a.x - b.x);
  const res = [];
  for (const s of ord) {
    const alvo = res.find((r) => Math.abs(r.y - s.y) < Math.max(r.size, s.size) * 0.45 && s.x >= r.x && s.x - (r.x + r.w) < Math.max(r.size, s.size) * 1.1 && s.x - (r.x + r.w) > -2 && r.bold === s.bold && !NUM.test(r.t));
    if (alvo && !NUM.test(s.t)) {
      const gap = s.x - (alvo.x + alvo.w);
      alvo.t += (gap > alvo.size * 0.12 || /[→|]$/.test(alvo.t) ? ' ' : '') + s.t;
      alvo.w = s.x + s.w - alvo.x;
    } else res.push({ ...s });
  }
  return res.sort((a, b) => a.y - b.y || a.x - b.x);
}

// Texto corrido: junta linhas e preserva parágrafos e marcadores.
function refluir(segs) {
  const ls = emLinhas(segs).filter((s) => s.t);
  const grupos = [];
  for (const s of ls) {
    const g = grupos[grupos.length - 1];
    if (g && Math.abs(g.y - s.y) < s.size * 0.45) { g.t += ' ' + s.t; continue; }
    grupos.push({ ...s });
  }
  let out = '', prev = null;
  for (const g of grupos) {
    if (!prev) out = g.t;
    else {
      const salto = g.y - prev.y > Math.max(prev.size, g.size) * 1.9;
      const marca = /^(•|-|–|\d{1,2}[.)])\s/.test(g.t) || /^[•\-–]$/.test(g.t);
      out += (salto || marca || /[:;]$/.test(prev.t) ? '\n' : ' ') + g.t;
    }
    prev = g;
  }
  return out.replace(/(^|\n)([•\-–])\s*\n/g, '$1$2 ').replace(/ {2,}/g, ' ').trim();
}

// Itens ancorados: cada âncora (número de passo ou título em negrito) "possui"
// os segmentos da sua coluna até a próxima âncora da mesma coluna.
function itensAncorados(ancoras, pool, regiao) {
  const cols = [];
  for (const a of [...ancoras].sort((p, q) => p.x - q.x)) {
    const col = cols.find((c) => Math.abs(c.x - a.x) < 30 || (a.x < c.x1 && a.x + a.w > c.x));
    if (col) { col.itens.push(a); col.x = Math.min(col.x, a.x); col.x1 = Math.max(col.x1, a.x + a.w); } else cols.push({ x: a.x, x1: a.x + a.w, itens: [a] });
  }
  cols.sort((p, q) => p.x - q.x);
  const usados = new Set();
  const itens = [];
  cols.forEach((c, ci) => {
    const xa = c.x - 10, xb = ci < cols.length - 1 ? cols[ci + 1].x - 10 : regiao.x1;
    c.itens.sort((p, q) => p.y - q.y);
    c.itens.forEach((a, k) => {
      const yb = k < c.itens.length - 1 ? c.itens[k + 1].y - 8 : regiao.y1;
      const meus = pool.filter((s) => !usados.has(s) && s !== a && s.x >= xa && s.x < xb && s.y >= a.y - 9 && s.y < yb);
      meus.forEach((s) => usados.add(s));
      itens.push({ a, meus });
    });
  });
  const resto = pool.filter((s) => !usados.has(s) && !ancoras.includes(s));
  return { itens, resto, colunas: cols.length };
}

function ordemLeitura(itens) {
  const numericos = itens.every((i) => NUM.test(i.a.t));
  if (numericos) return itens.sort((p, q) => +p.a.t - +q.a.t);
  return itens.sort((p, q) => (Math.abs(p.a.y - q.a.y) < 20 ? p.a.x - q.a.x : p.a.y - q.a.y));
}

function blocoPassos(rotulo, segs, regiao) {
  const ls = emLinhas(segs);
  let ancoras = ls.filter((s) => NUM.test(s.t) && s.size <= 18);
  if (!ancoras.length) ancoras = ls.filter((s) => s.bold && !NUM.test(s.t));
  if (!ancoras.length) return [{ tipo: 'texto', rotulo, titulo: '', texto: refluir(segs) }];
  const { itens, resto } = itensAncorados(ancoras, ls.filter((s) => !ancoras.includes(s)), regiao);
  const out = ordemLeitura(itens).map(({ a, meus }) => {
    const ordem = emLinhas(meus);
    let tit = ordem.filter((s) => s.bold), corpo = ordem.filter((s) => !s.bold);
    if (!NUM.test(a.t)) { tit = [a, ...tit]; }
    if (!tit.length && corpo.length) { tit = [corpo[0]]; corpo = corpo.slice(1); }
    return { t: refluir(tit), d: refluir(corpo) };
  }).filter((i) => i.t || i.d);
  const blocos = [{ tipo: 'passos', rotulo, itens: out }];
  if (resto.length) blocos.push({ tipo: 'texto', rotulo: '', titulo: '', texto: refluir(resto) });
  return blocos;
}

// Títulos em negrito quebrados em várias linhas viram uma âncora só.
function juntarAncoras(ancoras) {
  const out = [];
  for (const a of [...ancoras].sort((p, q) => p.y - q.y || p.x - q.x)) {
    const prev = out.filter((o) => Math.abs(o.x - a.x) < 30 && a.y > o.yFim && a.y - o.yFim < o.size * 1.7).pop();
    if (prev) { prev.t += ' ' + a.t; prev.w = Math.max(prev.w, a.w); prev.yFim = a.y; prev.juntou.push(a); }
    else out.push({ ...a, yFim: a.y, juntou: [a] });
  }
  return out;
}

// Tabela a partir de uma grade: colunas pelos títulos, linhas pela posição vertical.
// Linha cuja 1ª célula está vazia é continuação da anterior (célula com várias linhas).
function grade(ls, ancoras) {
  const xs = [...new Set(ancoras.map((a) => Math.round(a.x)))].sort((a, b) => a - b)
    .filter((x, i, arr) => i === 0 || x - arr[i - 1] > 30);
  const colDe = (s) => { let c = 0; xs.forEach((x, i) => { if (s.x >= x - 12) c = i; }); return c; };
  const linhas = [];
  let atual = null, yAtual = -99;
  for (const s of [...ls].sort((a, b) => a.y - b.y || a.x - b.x)) {
    if (!atual || s.y - yAtual > s.size * 0.6) {
      if (!atual || colDe(s) === 0) { atual = Array(xs.length).fill(''); linhas.push(atual); }
      yAtual = s.y;
    }
    const c = colDe(s);
    atual[c] = atual[c] ? atual[c] + ' ' + s.t : s.t;
  }
  return linhas;
}

// Texto livre: vira cartões (títulos em negrito em 2+ colunas), textos com título ou texto corrido.
function blocosLivres(segs, regiao, rotulo = '', centro = false) {
  if (!segs.length) return [];
  const ls0 = emLinhas(segs);
  const brutas = ls0.filter((s) => s.bold && s.t.length > 1 && !NUM.test(s.t) && !ehFonte(s.t));
  const ancoras = juntarAncoras(brutas);
  const ls = [...ls0.filter((s) => !brutas.includes(s)), ...ancoras];
  if (ancoras.length && brutas.length < ls0.length) {
    const { itens, resto, colunas } = itensAncorados(ancoras, ls.filter((s) => !ancoras.includes(s)), regiao);
    const ord = ordemLeitura(itens).map(({ a, meus }) => ({ t: a.t, d: refluir(meus) }));
    if (colunas >= 3 && !centro) return [{ tipo: 'tabela', rotulo, linhas: grade(ls, ancoras) }];
    const pre = resto.length ? [{ tipo: 'texto', rotulo, titulo: '', texto: refluir(resto) }] : [];
    if (colunas >= 2 && !centro && ord.length >= 2) {
      return [...pre, { tipo: 'cards', rotulo: pre.length ? '' : rotulo, estilo: 'lateral', itens: ord }];
    }
    // Uma coluna: títulos seguidos sem descrição se juntam (ex.: listas de nomes).
    const blocos = [...pre];
    let acum = [];
    ord.forEach((it, i) => {
      if (!it.d && i < ord.length - 1) { acum.push(it.t); return; }
      blocos.push({ tipo: 'texto', rotulo: blocos.length ? '' : rotulo, titulo: [...acum, it.t].join('\n'), texto: it.d });
      acum = [];
    });
    return blocos;
  }
  return [{ tipo: 'texto', rotulo, titulo: '', texto: refluir(segs) }];
}

export function classificar({ segs: brutos, imgs, tabs }, indice, total, original) {
  const avisos = [];
  const W = A4.w;
  // Duplicatas exatas (texto repetido na mesma posição) e sobreposições.
  const segs = [];
  for (const s of brutos) {
    if (segs.some((o) => o.t === s.t && Math.abs(o.x - s.x) < 2 && Math.abs(o.y - s.y) < 2)) continue;
    segs.push(s);
  }
  let sobrepostos = 0;
  for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) {
    const a = segs[i], b = segs[j];
    const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), iy = Math.min(a.y + a.size, b.y + b.size) - Math.max(a.y, b.y);
    if (ix > Math.min(a.w, b.w) * 0.5 && iy > Math.min(a.size, b.size) * 0.5 && a.t !== b.t) sobrepostos++;
  }
  if (sobrepostos) avisos.push(`${sobrepostos} trecho(s) de texto sobreposto(s) no original — confira a ordem do conteúdo.`);

  // Cabeçalho e rodapé antigos saem: são redesenhados no padrão.
  const faq = [];
  let pool = segs.filter((s) => {
    const n = sem(s.t);
    if (s.y < 62) {
      (s.t.match(/FAQ\s*\d+/gi) || []).forEach((f) => faq.push(f.toUpperCase().replace(/\s+/, ' ')));
      if (/GUIA\s*SIGAA|^FAQ\s*\d+$/.test(n) || /^(FAQ\s*\d+\s*)+$/.test(n)) return false;
    }
    if (s.y > 806) return false;
    if (s.y > 770 && (/^DIOAC \| PROEN/.test(n) || /^SUMARIO\b/.test(n) || /^\(SIGAA, ?\d{4}\)$/.test(n))) return false;
    return true;
  });
  const imagens = imgs.filter((im) => !(im.y < 90 && im.x > W * 0.7 && im.w < 110));

  // Capa: primeira página com pouco texto.
  if (indice === 0 && emLinhas(pool).length <= 12) {
    const ls = emLinhas(segs).filter((s) => s.y < 806 || /DIOAC|SIGAA/.test(s.t)).map((s) => s.t);
    const guia = ls.find((t) => /GUIA/i.test(t)) || 'GUIA SIGAA';
    const rod = ls.filter((t) => /DIOAC|PROEN|UFMA|\(SIGAA|^\d{4}$/.test(t) && t !== guia);
    const resto = ls.filter((t) => t !== guia && !rod.includes(t));
    return { tipo: 'capa', guia, subtitulo: resto[0] || '', descricao: resto.slice(1).join(' '), rodape: rod.join('\n'), blocos: [], faq: '', original, avisos, confianca: 'alta' };
  }

  pool = emLinhas(pool);
  // Seção e título.
  let secao = '', titulo = '';
  const grandeTopo = pool.some((s) => s.y < 140 && s.size >= 14);
  const secSeg = grandeTopo ? null : pool.find((s) => s.y < 150 && (SECOES.some((x) => sem(s.t) === sem(x.nome)) || /^FAQ\s*\|/.test(sem(s.t))));
  if (secSeg) {
    secao = secSeg.t.replace(/\s*\|\s*/g, ' | ');
    pool = pool.filter((s) => s !== secSeg);
    const tit = pool.filter((s) => s.y > secSeg.y && s.y < secSeg.y + 60 && !rotuloDe(s) && !NUM.test(s.t)).sort((a, b) => a.y - b.y)[0];
    if (tit && (tit.bold || tit.size >= secSeg.size) && !/^\d{1,3}[.)]\s/.test(tit.t)) { titulo = tit.t; pool = pool.filter((s) => s !== tit); }
  } else {
    const grande = pool.filter((s) => s.y < 230 && s.size >= 14).sort((a, b) => b.size - a.size || a.y - b.y)[0];
    if (grande) {
      const mesmas = pool.filter((s) => Math.abs(s.size - grande.size) < 0.5 && Math.abs(s.y - grande.y) < grande.size * 2.6 && s.bold === grande.bold);
      titulo = refluir(mesmas); pool = pool.filter((s) => !mesmas.includes(s));
    } else avisos.push('Seção e título não reconhecidos.');
  }

  // Legendas "Fonte: ..." vão para a imagem mais próxima acima.
  for (const f of pool.filter((s) => ehFonte(s.t))) {
    const im = imagens.filter((i) => i.y + i.h <= f.y + 6 && f.y - (i.y + i.h) < 60).sort((a, b) => b.y - a.y)[0];
    if (im) { im.legenda = f.t; pool = pool.filter((s) => s !== f); }
  }

  // Rótulos (âncoras de região).
  const rotulos = [];
  for (const s of pool) {
    const r = rotuloDe(s);
    if (!r) continue;
    rotulos.push({ ...r, seg: s, y: s.y, x: s.x, x1: s.x + s.w });
  }
  pool = pool.filter((s) => !rotulos.some((r) => r.seg === s));

  const blocos = []; // { y, col, bloco }

  // Caminho: linhas com seta perto do rótulo (acima, ao lado ou abaixo).
  for (const r of rotulos.filter((r) => r.tipo === 'caminho')) {
    const xLim = r.x + Math.min(r.seg.w, 120) - 6;
    const perto = pool.filter((s) => Math.abs(s.y - r.y) <= 34 && s.x >= xLim);
    const linhas = [];
    if (r.resto) linhas.push(r.resto);
    const grupos = [];
    for (const s of emLinhas(perto)) {
      const g = grupos.find((g) => Math.abs(g.y - s.y) < s.size * 0.45);
      if (g) g.t += ' ' + s.t; else grupos.push({ ...s });
    }
    grupos.sort((a, b) => a.y - b.y).forEach((g) => {
      if (!g.t.includes('→') && linhas.length && !/^[A-ZÁ-Ú][a-zá-ú]+ →/.test(g.t)) linhas[linhas.length - 1] += ' ' + g.t;
      else linhas.push(g.t);
    });
    pool = pool.filter((s) => !perto.includes(s));
    blocos.push({ y: r.y, col: 'cheio', bloco: { tipo: 'caminho', linhas: linhas.length ? linhas : [''] } });
  }

  // Regiões dos demais rótulos.
  const regs = rotulos.filter((r) => r.tipo !== 'caminho').map((r) => {
    const dir = r.x >= W * 0.45;
    const vizDir = !dir && rotulos.some((o) => o !== r && o.x >= W * 0.45 && Math.abs(o.y - r.y) < 25);
    const col = dir ? 'dir' : vizDir ? 'esq' : 'cheio';
    return { ...r, col, x0: dir ? W * 0.45 - 10 : 0, x1: col === 'esq' ? W * 0.5 : W };
  });
  regs.forEach((r) => {
    const abaixo = regs.filter((o) => o !== r && o.y > r.y + 2 && (r.col === 'dir' ? o.col !== 'esq' || o.x0 < r.x1 : o.col !== 'dir'));
    r.y1 = Math.min(806, ...abaixo.map((o) => o.y), ...blocos.filter((b) => b.y > r.y + 2).map((b) => b.y - 34));
    r.segs = []; r.imgs = [];
  });
  const regiaoDe = (x, y) => regs.filter((r) => x >= r.x0 && x < r.x1 && y >= r.y - 4 && y < r.y1).sort((a, b) => b.y - a.y)[0];
  const livres = [];
  for (const s of pool) { const r = regiaoDe(s.x, s.y); if (r) r.segs.push(s); else livres.push(s); }
  const imgsLivres = [];
  for (const im of imagens) { const r = regiaoDe(im.x + Math.min(im.w, 40) / 2, im.y); if (r) r.imgs.push(im); else imgsLivres.push(im); }
  const blocoImg = (im, rotulo) => ({ tipo: 'imagem', rotulo, src: im.src, iw: im.iw, ih: im.ih, legenda: im.legenda || '' });

  for (const r of regs) {
    const reg = { x1: r.x1, y1: r.y1 };
    const rot = r.seg.t.slice(0, r.txt.length).trim() || r.txt;
    let bs = [];
    if (r.tipo === 'passos') bs = blocoPassos(rot, r.segs, reg);
    else if (r.tipo === 'imagem') {
      bs = r.imgs.map((im, i) => blocoImg(im, i === 0 ? rot : ''));
      if (!bs.length) bs = [{ ...blocoVazio('imagem'), rotulo: rot }];
      r.imgs = [];
      if (r.segs.length) bs.push(...blocosLivres(r.segs, reg));
    } else if (['observacao', 'regulamentacao', 'atencao', 'destaque'].includes(r.tipo)) {
      const txt = [r.resto, refluir(r.segs)].filter(Boolean).join('\n');
      bs = [{ tipo: 'quadro', variante: r.tipo, rotulo: rot, texto: txt }];
    } else {
      bs = blocosLivres(r.segs, reg, rot);
      if (r.resto && bs[0]?.tipo === 'texto') bs[0].texto = (r.resto + '\n' + bs[0].texto).trim();
      if (!bs.length) bs = [{ tipo: 'texto', rotulo: rot, titulo: '', texto: r.resto || '' }];
    }
    bs.forEach((b, i) => blocos.push({ y: r.y + i * 0.01, col: r.col, bloco: b }));
    r.imgs.forEach((im, i) => blocos.push({ y: im.y + i * 0.01, col: 'cheio', bloco: blocoImg(im, '') }));
  }

  // Texto fora de regiões: agrupado por faixas verticais (separadas por blocos já posicionados).
  const centro = livres.length >= 4 && livres.filter((s) => Math.abs(s.x + s.w / 2 - W / 2) < 22).length >= livres.length * 0.7;
  if (livres.length) {
    const cortes = [...new Set(blocos.map((b) => b.y))].sort((a, b) => a - b);
    const faixas = new Map();
    for (const s of livres) {
      const k = cortes.filter((c) => c <= s.y).length;
      if (!faixas.has(k)) faixas.set(k, []);
      faixas.get(k).push(s);
    }
    for (const [, ss] of faixas) {
      const y0 = Math.min(...ss.map((s) => s.y));
      blocosLivres(ss, { x1: W, y1: 806 }, '', centro).forEach((b, i) => blocos.push({ y: y0 + i * 0.01, col: 'cheio', bloco: b }));
    }
  }
  imgsLivres.forEach((im) => blocos.push({ y: im.y, col: 'cheio', bloco: blocoImg(im, im.legenda ? 'TELA DO SIGAA' : '') }));
  (tabs || []).forEach((t) => blocos.push({ y: t.y, col: 'cheio', bloco: { tipo: 'tabela', rotulo: '', linhas: t.linhas } }));

  blocos.sort((a, b) => a.y - b.y);
  // Quadros da coluna direita ficam logo após os passos ao lado dos quais estavam.
  const final = [];
  for (const b of blocos) {
    if (b.bloco.tipo === 'quadro' && b.col === 'dir') {
      const iP = final.map((f) => f.bloco.tipo).lastIndexOf('passos');
      if (iP >= 0) { let k = iP + 1; while (final[k]?.bloco.tipo === 'quadro') k++; final.splice(k, 0, b); continue; }
    }
    final.push(b);
  }

  const lista = final.map((b) => b.bloco).filter((b) => !(b.tipo === 'texto' && !b.texto && !b.titulo && !b.rotulo));
  const conf = rotulos.length ? 'alta' : lista.length ? 'media' : 'baixa';
  if (!rotulos.length && lista.length && !secao) avisos.push('Nenhum rótulo do modelo (Caminho, Como fazer, Observação…) reconhecido: revise a estrutura.');
  if (!lista.length && !titulo) avisos.push('Página sem conteúdo reconhecível.');
  return {
    tipo: 'conteudo', secao, titulo, faq: [...new Set(faq)].join(', '), alinhamento: centro ? 'centro' : 'esquerda',
    blocos: lista, original, avisos, confianca: conf,
  };
}
