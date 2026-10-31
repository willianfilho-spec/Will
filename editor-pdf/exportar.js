// Gravação com pdf-lib (carregado como script global em window.PDFLib).
// As anotações são "achatadas": viram conteúdo desenhado na página
// (não são objetos de anotação do PDF e não podem ser editadas depois em outro leitor).
const ASC = 0.8, LINHA = 1.2;

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

// Remove caracteres que a fonte padrão (WinAnsi) não consegue gravar.
function higienizar(fonte, texto) {
  let out = '';
  for (const ch of texto) {
    try { fonte.encodeText(ch); out += ch; } catch { out += '?'; }
  }
  return out;
}

function bytesDeDataUrl(url) {
  const b64 = url.slice(url.indexOf(',') + 1);
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}

/**
 * @param {Uint8Array} original bytes do PDF aberto
 * @param {{w:number,h:number,transform:number[]}[]} paginas viewport (escala 1) de cada página, vindo do pdf.js
 * @param {object[]} anotacoes coordenadas em pontos, origem no canto superior esquerdo da página exibida
 */
export async function gerarPdfAnotado(original, paginas, anotacoes) {
  const { PDFDocument, StandardFonts, BlendMode, LineCapStyle, pushGraphicsState, popGraphicsState, concatTransformationMatrix, rgb } = PDFLib;
  const doc = await PDFDocument.load(original);
  const fonte = await doc.embedFont(StandardFonts.Helvetica);
  const imagens = new Map();
  const porPagina = new Map();
  for (const a of anotacoes) { if (!porPagina.has(a.pagina)) porPagina.set(a.pagina, []); porPagina.get(a.pagina).push(a); }

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

    const texto = (a, x, yTopo) => a.texto.split('\n').forEach((l, k) => {
      page.drawText(higienizar(fonte, l), { x, y: H - (yTopo + a.tamanho * (ASC + k * LINHA)), size: a.tamanho, font: fonte, color: corPdf(a.cor) });
    });

    for (const a of lista) {
      switch (a.tipo) {
        case 'texto': texto(a, a.x, a.y); break;
        case 'cobrir':
          page.drawRectangle({ x: a.x, y: H - a.y - a.h, width: a.w, height: a.h, color: rgb(1, 1, 1) });
          if (a.texto) texto(a, a.x + 2, a.y + 2);
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
