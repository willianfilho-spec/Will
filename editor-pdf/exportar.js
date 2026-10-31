// Gravação com pdf-lib (carregado como script global em window.PDFLib; fontkit em window.fontkit).
// As anotações são "achatadas": viram conteúdo desenhado na página
// (não são objetos de anotação do PDF e não podem ser editadas depois em outro leitor).
import { LINHA, esquerdaDoTexto, baseDoTexto, larguraUtil, corDoFundo, urlFonte } from './texto.js';

function corPdf(hex) {
  const n = parseInt(String(hex || '#000000').slice(1), 16);
  return PDFLib.rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

// Multiplicação de matrizes afins no formato PDF [a b c d e f] (vetor-linha: p' = p × M).
function multiplicar(A, B) {
  return [A[0] * B[0] + A[1] * B[2], A[0] * B[1] + A[1] * B[3],
    A[2] * B[0] + A[3] * B[2], A[2] * B[1] + A[3] * B[3],
    A[4] * B[0] + A[5] * B[2] + B[4], A[4] * B[1] + A[5] * B[3] + B[5]];
}
function inverter([a, b, c, d, e, f]) {
  const det = a * d - b * c;
  return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det];
}

function bytesDeDataUrl(url) {
  const b64 = url.slice(url.indexOf(',') + 1);
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}

// Fontes padrão do PDF (sem embutir) na ordem [normal, negrito, itálico, negrito+itálico].
const PADRAO = {
  helvetica: ['Helvetica', 'HelveticaBold', 'HelveticaOblique', 'HelveticaBoldOblique'],
  times: ['TimesRoman', 'TimesRomanBold', 'TimesRomanItalic', 'TimesRomanBoldItalic'],
  courier: ['Courier', 'CourierBold', 'CourierOblique', 'CourierBoldOblique'],
};

/** Devolve { pdf, limpar(texto) }: a fonte do pdf-lib e uma função que troca por "?" o que a fonte não consegue gravar. */
async function obterFonte(doc, cache, fonte = 'helvetica', negrito = false, italico = false) {
  const chave = `${fonte}|${!!negrito}|${!!italico}`;
  if (cache.has(chave)) return cache.get(chave);
  let r;
  if (fonte === 'sans') {
    if (!window.fontkit) throw new Error('fontkit não carregado');
    if (!cache.has('fk')) { doc.registerFontkit(window.fontkit); cache.set('fk', true); }
    const arq = `${negrito ? 700 : 400}-${italico ? 'italic' : 'normal'}`;
    const bytes = new Uint8Array(await (await fetch(urlFonte(arq))).arrayBuffer());
    const fk = window.fontkit.create(bytes);
    const pdf = await doc.embedFont(bytes, { subset: true });
    r = { pdf, limpar: t => [...t].map(ch => (fk.hasGlyphForCodePoint(ch.codePointAt(0)) ? ch : '?')).join('') };
  } else {
    const nomes = PADRAO[fonte] || PADRAO.helvetica;
    const pdf = await doc.embedFont(PDFLib.StandardFonts[nomes[(negrito ? 1 : 0) + (italico ? 2 : 0)]]);
    r = { pdf, limpar: t => [...t].map(ch => { try { pdf.encodeText(ch); return ch; } catch { return '?'; } }).join('') };
  }
  cache.set(chave, r);
  return r;
}

/**
 * @param {Uint8Array} original bytes do PDF aberto
 * @param {{w:number,h:number,transform:number[]}[]} paginas viewport (escala 1) de cada página, vindo do pdf.js
 * @param {object[]} anotacoes coordenadas em pontos, origem no canto superior esquerdo da página exibida
 * @param {{rasterizadas?: Map<number, Uint8Array>}} opcoes `rasterizadas`: índice da página -> JPEG da página já com as
 *   anotações. Essas páginas são SUBSTITUÍDAS por uma página só de imagem (o texto original deixa de existir no arquivo).
 */
export async function gerarPdfAnotado(original, paginas, anotacoes, opcoes = {}) {
  const { PDFDocument, BlendMode, LineCapStyle, pushGraphicsState, popGraphicsState, concatTransformationMatrix } = PDFLib;
  const raster = opcoes.rasterizadas || new Map();
  const doc = await PDFDocument.load(original);
  const fontes = new Map();
  const imagens = new Map();
  const porPagina = new Map();
  for (const a of anotacoes) { if (raster.has(a.pagina)) continue; if (!porPagina.has(a.pagina)) porPagina.set(a.pagina, []); porPagina.get(a.pagina).push(a); }

  for (const [idx, lista] of porPagina) {
    const page = doc.getPage(idx);
    const { h: H, transform } = paginas[idx];
    // Isola o conteúdo original (q ... Q) e abre um fluxo novo depois dele.
    page.translateContent(0, 0);
    page.resetPosition();
    // Espaço local "y para cima" do tamanho da página exibida -> espaço do PDF
    // (cobre /Rotate, CropBox deslocada e origem diferente de 0,0).
    const M = multiplicar([1, 0, 0, -1, 0, H], inverter(transform));
    page.pushOperators(pushGraphicsState(), concatTransformationMatrix(...M));

    // Fundo do bloco: cor única, degradê vertical ou colunas de degradês verticais. Sem emendas: cada camada pinta até a
    // base (e, nas colunas, até a borda direita) da caixa, e a seguinte cobre a anterior (o antialiasing entre faixas finas
    // deixava aparecer o texto antigo por baixo).
    const pintarFundo = a => {
      const fundo = a.fundo || '#ffffff';
      const cor = c => corPdf(c);
      if (typeof fundo === 'string') { page.drawRectangle({ x: a.x, y: H - a.y - a.h, width: a.w, height: a.h, color: cor(fundo) }); return; }
      const colunas = Array.isArray(fundo[0]) ? fundo : [fundo];
      const n = Math.max(2, Math.min(40, Math.ceil(a.h / 0.75)));
      colunas.forEach((col, c) => {
        const x = a.x + a.w * c / colunas.length, larg = a.x + a.w - x;
        if (col.length === 1) { page.drawRectangle({ x, y: H - a.y - a.h, width: larg, height: a.h, color: cor(col[0]) }); return; }
        for (let k = 0; k < n; k++) {
          const topo = a.y + k * a.h / n;
          page.drawRectangle({ x, y: H - a.y - a.h, width: larg, height: a.y + a.h - topo, color: cor(corDoFundo(col, (k + 0.5) / n)) });
        }
      });
    };

    const texto = async a => {
      if (!a.texto) return;
      const f = await obterFonte(doc, fontes, a.fonte || 'helvetica', a.negrito, a.italico);
      const L = esquerdaDoTexto(a), base0 = baseDoTexto(a), util = larguraUtil(a);
      a.texto.split('\n').forEach((l, k) => {
        const s = f.limpar(l);
        let x = L;
        if (util && a.alinhar && a.alinhar !== 'esq') {
          const lw = f.pdf.widthOfTextAtSize(s, a.tamanho);
          x = a.alinhar === 'centro' ? L + (util - lw) / 2 : L + util - lw;
        }
        page.drawText(s, { x, y: H - (base0 + k * LINHA * a.tamanho), size: a.tamanho, font: f.pdf, color: corPdf(a.cor) });
      });
    };

    for (const a of lista) {
      switch (a.tipo) {
        case 'texto': await texto(a); break;
        case 'cobrir': case 'edicao':
          pintarFundo(a);
          await texto(a);
          break;
        case 'destaque':
          page.drawRectangle({ x: a.x, y: H - a.y - a.h, width: a.w, height: a.h, color: corPdf(a.cor), opacity: 0.4, blendMode: BlendMode.Multiply });
          break;
        case 'retangulo':
          page.drawRectangle({ x: a.x, y: H - a.y - a.h, width: a.w, height: a.h, borderColor: corPdf(a.cor), borderWidth: a.espessura });
          break;
        case 'elipse':
          page.drawEllipse({ x: a.x + a.w / 2, y: H - a.y - a.h / 2, xScale: a.w / 2, yScale: a.h / 2, borderColor: corPdf(a.cor), borderWidth: a.espessura });
          break;
        case 'linha':
          page.drawLine({ start: { x: a.x1, y: H - a.y1 }, end: { x: a.x2, y: H - a.y2 }, thickness: a.espessura, color: corPdf(a.cor), lineCap: LineCapStyle.Round });
          break;
        case 'desenho': {
          const d = a.pontos.map(([x, y], k) => `${k ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' ') + (a.pontos.length === 1 ? ' l0.01 0' : '');
          page.drawSvgPath(d, { x: 0, y: H, borderColor: corPdf(a.cor), borderWidth: a.espessura, borderLineCap: LineCapStyle.Round });
          break;
        }
        case 'imagem': {
          let img = imagens.get(a.dataUrl);
          if (!img) {
            const bytes = bytesDeDataUrl(a.dataUrl);
            img = a.dataUrl.startsWith('data:image/jpeg') ? await doc.embedJpg(bytes) : await doc.embedPng(bytes);
            imagens.set(a.dataUrl, img);
          }
          page.drawImage(img, { x: a.x, y: H - a.y - a.h, width: a.w, height: a.h });
          break;
        }
      }
    }
    page.pushOperators(popGraphicsState());
  }

  // Páginas rasterizadas: troca a página original por uma página só de imagem, do mesmo tamanho exibido.
  for (const [idx, jpeg] of raster) {
    const { w, h } = paginas[idx];
    const nova = doc.insertPage(idx, [w, h]);
    nova.drawImage(await doc.embedJpg(jpeg), { x: 0, y: 0, width: w, height: h });
    doc.removePage(idx + 1);
  }
  return doc.save();
}

/** Novo PDF só com as páginas indicadas (índices a partir de 0), na ordem dada. */
export async function gerarPdfComPaginas(origem, indices) {
  const { PDFDocument } = PDFLib;
  const src = await PDFDocument.load(origem);
  const novo = await PDFDocument.create();
  const copiadas = await novo.copyPages(src, indices);
  copiadas.forEach(p => novo.addPage(p));
  return novo.save();
}
