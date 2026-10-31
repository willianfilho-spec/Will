// OCR no navegador com tesseract.js (Apache-2.0), tudo local em vendor/tesseract/ (sem CDN).
// Carregado sob demanda: nada disto é baixado nem iniciado ao abrir o app ou um PDF.
const BASE = new URL('./vendor/tesseract/', import.meta.url);
let promessaTrabalhador = null;
let ouvinte = null;

function trabalhador() {
  promessaTrabalhador ??= (async () => {
    const m = await import('./vendor/tesseract/tesseract.esm.min.js');
    const T = m.createWorker ? m : (m.default?.createWorker ? m.default : m);
    return T.createWorker(['por', 'eng'], 1 /* só LSTM */, {
      workerPath: new URL('worker.min.js', BASE).href,
      corePath: new URL('tesseract-core-simd-lstm.wasm.js', BASE).href, // arquivo único (.js): evita a busca no CDN
      langPath: new URL('lang', BASE).href,
      cacheMethod: 'none',
      workerBlobURL: false,
      logger: m => ouvinte?.(m),
    });
  })().catch(e => { promessaTrabalhador = null; throw e; });
  return promessaTrabalhador;
}

/**
 * Reconhece o texto de um canvas. `aoProgresso(0..1, rotulo)` recebe o andamento.
 * Devolve linhas { texto, caixa:{x0,y0,x1,y1} (px do canvas), baseY|null, confianca (0-100), palavras:[{texto,caixa,confianca}] }.
 */
export async function reconhecerCanvas(canvas, aoProgresso = () => {}) {
  aoProgresso(0, 'Carregando o reconhecedor…');
  const w = await trabalhador();
  ouvinte = m => {
    if (m.status === 'recognizing text') aoProgresso(0.15 + 0.85 * (m.progress ?? 0), 'Reconhecendo o texto…');
    else if (/loading|initializ/.test(m.status || '')) aoProgresso(Math.min(0.15, (m.progress ?? 0) * 0.15), 'Carregando o reconhecedor…');
  };
  try {
    const r = await w.recognize(canvas, {}, { blocks: true });
    const linhas = [];
    for (const b of r.data.blocks || []) for (const p of b.paragraphs || []) for (const l of p.lines || []) {
      const texto = (l.text || '').replace(/\s+/g, ' ').trim();
      if (!texto) continue;
      const bl = l.baseline && l.baseline.has_baseline ? l.baseline : null;
      linhas.push({
        texto, caixa: { ...l.bbox }, confianca: l.confidence ?? 0,
        baseline: bl ? { x0: bl.x0, y0: bl.y0, x1: bl.x1, y1: bl.y1 } : null,
        palavras: (l.words || []).map(pa => ({ texto: pa.text, caixa: { ...pa.bbox }, confianca: pa.confidence ?? 0 })),
      });
    }
    aoProgresso(1, 'Pronto');
    return linhas;
  } finally { ouvinte = null; }
}
