#!/usr/bin/env node
// Verificador de fluxos: executa no Chromium os passos de um arquivo JSON
// e gera relatório + capturas. Uso: node verificar.mjs <arquivo.json>
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile, stat, rm } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
  '.pdf': 'application/pdf', '.wasm': 'application/wasm', '.ttf': 'font/ttf' };

function servir(pasta) {
  const raiz = path.resolve(pasta);
  const srv = createServer(async (req, res) => {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let arq = path.join(raiz, p);
    if (!arq.startsWith(raiz)) { res.writeHead(403).end(); return; }
    try { if ((await stat(arq)).isDirectory()) arq = path.join(arq, 'index.html'); 
      res.writeHead(200, { 'content-type': MIME[path.extname(arq)] || 'application/octet-stream' });
      res.end(await readFile(arq));
    } catch { res.writeHead(404).end('404'); }
  });
  return new Promise(r => srv.listen(0, '127.0.0.1', () => r(srv)));
}

// Caixa do elemento + ponto relativo (frações 0..1 da largura/altura).
async function pontoEm(page, sel, [fx, fy], t) {
  const loc = page.locator(sel).first();
  await loc.waitFor({ state: 'visible', timeout: t });
  await loc.scrollIntoViewIfNeeded();
  let b = await loc.boundingBox();
  // Elementos altos (ex.: página de PDF): rola até o ponto ficar no meio da tela,
  // longe de cabeçalhos fixos e da borda inferior.
  const alt = page.viewportSize().height, y = b.y + b.height * fy;
  if (y < alt * 0.25 || y > alt * 0.85) {
    await page.evaluate(d => window.scrollBy(0, d), y - alt / 2);
    b = await loc.boundingBox();
  }
  return { x: b.x + b.width * fx, y: b.y + b.height * fy };
}

// Abre o PDF baixado no próprio Chromium com o pdf.js indicado em spec.pdfjs
// (servido pelo app, mesma origem) e devolve { paginas, texto, textoPorPagina, amostras, imagem }.
// `amostras` = [{ pagina, fx, fy }] -> cor RGB do pixel na fração (fx, fy) da página renderizada (escala 1).
// `capturaPagina` = n -> PNG (base64) da página n renderizada em escala 1,5.
async function lerPdfNoNavegador(page, spec, base, bytes, extra = {}) {
  if (!spec.pdfjs) throw new Error('Validação de PDF requer "pdfjs" e "pdfjsWorker" no arquivo de fluxos');
  const aux = await page.context().newPage();
  try {
    const mod = new URL(spec.pdfjs, base).href;
    await aux.goto(mod);
    return await aux.evaluate(async ({ mod, worker, b64, amostras, capturaPagina }) => {
      const pdfjs = await import(mod);
      pdfjs.GlobalWorkerOptions.workerSrc = worker;
      const data = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const doc = await pdfjs.getDocument({ data }).promise;
      let texto = ''; const textoPorPagina = [];
      for (let i = 1; i <= doc.numPages; i++) {
        const tc = await (await doc.getPage(i)).getTextContent();
        const t = tc.items.map(it => it.str).join(' ');
        textoPorPagina.push(t); texto += t + '\n';
      }
      const renderizar = async (n, escala) => {
        const pg = await doc.getPage(n), vp = pg.getViewport({ scale: escala });
        const c = document.createElement('canvas'); c.width = Math.floor(vp.width); c.height = Math.floor(vp.height);
        await pg.render({ canvasContext: c.getContext('2d'), canvas: c, viewport: vp }).promise;
        return c;
      };
      const res = [];
      for (const a of amostras || []) {
        const c = await renderizar(a.pagina, 1);
        const x = Math.min(c.width - 1, Math.floor(c.width * a.fx)), y = Math.min(c.height - 1, Math.floor(c.height * a.fy));
        res.push(Array.from(c.getContext('2d').getImageData(x, y, 1, 1).data.slice(0, 3)));
      }
      let imagem = null;
      if (capturaPagina) imagem = (await renderizar(capturaPagina, 1.5)).toDataURL('image/png').split(',')[1];
      return { paginas: doc.numPages, texto, textoPorPagina, amostras: res, imagem };
    }, { mod, worker: new URL(spec.pdfjsWorker, base).href, b64: bytes.toString('base64'), amostras: extra.amostras, capturaPagina: extra.capturaPagina });
  } finally { await aux.close(); }
}

const hexRgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));

async function validarDownload(page, spec, base, arq, v) {
  const bytes = await readFile(arq);
  const nome = path.basename(arq);
  if (v.nomeContem && !nome.includes(v.nomeContem)) throw new Error(`download "${nome}" não contém "${v.nomeContem}" no nome`);
  if (v.bytesMin && bytes.length < v.bytesMin) throw new Error(`download "${nome}" tem ${bytes.length} bytes (< ${v.bytesMin})`);
  if (v.bytesMax && bytes.length > v.bytesMax) throw new Error(`download "${nome}" tem ${bytes.length} bytes (> ${v.bytesMax})`);
  if (v.textoContem) for (const s of [].concat(v.textoContem)) {
    if (!bytes.toString('utf8').includes(s)) throw new Error(`texto de "${nome}" não contém "${s}"`);
  }
  if (v.assinatura && !bytes.subarray(0, 8).toString('latin1').includes(v.assinatura))
    throw new Error(`"${nome}" não começa com "${v.assinatura}"`);
  if (v.pdfPaginas !== undefined || v.pdfTextoContem || v.pdfTextoNaoContem || v.pdfAmostras || v.pdfCapturaPagina) {
    const pdf = await lerPdfNoNavegador(page, spec, base, bytes, { amostras: v.pdfAmostras, capturaPagina: v.pdfCapturaPagina });
    if (pdf.imagem) await writeFile(arq.replace(/\.pdf$/i, '') + `-pagina${v.pdfCapturaPagina}.png`, Buffer.from(pdf.imagem, 'base64'));
    if (v.pdfPaginas !== undefined && pdf.paginas !== v.pdfPaginas) throw new Error(`PDF "${nome}": esperado ${v.pdfPaginas} página(s), tem ${pdf.paginas}`);
    for (const s of [].concat(v.pdfTextoContem || [])) if (!pdf.texto.includes(s)) throw new Error(`PDF "${nome}" não contém o texto "${s}"`);
    for (const s of [].concat(v.pdfTextoNaoContem || [])) if (pdf.texto.includes(s)) throw new Error(`PDF "${nome}" não deveria conter "${s}"`);
    // Amostras de pixel da página renderizada: { pagina, fx, fy, perto: "#rrggbb", tolerancia } ou { ..., longe: "#rrggbb", tolerancia }
    (v.pdfAmostras || []).forEach((a, k) => {
      const [r, g, b] = pdf.amostras[k], tol = a.tolerancia ?? 40;
      const d = ref => { const q = hexRgb(ref); return Math.max(Math.abs(r - q[0]), Math.abs(g - q[1]), Math.abs(b - q[2])); };
      if (a.perto && d(a.perto) > tol) throw new Error(`PDF "${nome}": pixel (${a.fx}, ${a.fy}) da página ${a.pagina} é rgb(${r},${g},${b}), esperado perto de ${a.perto} (±${tol})`);
      if (a.longe && d(a.longe) <= tol) throw new Error(`PDF "${nome}": pixel (${a.fx}, ${a.fy}) da página ${a.pagina} é rgb(${r},${g},${b}), não deveria estar perto de ${a.longe}`);
    });
  }
}

async function executarPasso(page, p, base, dirSaida, fluxoIdx, capturas, spec) {
  const t = p.tempo || 5000;
  if (p.ir !== undefined) return page.goto(new URL(p.ir, base).href);
  if (p.selecionar) return page.selectOption(p.selecionar, String(p.valor), { timeout: t });
  if (p.passar) { const pt = await pontoEm(page, p.passar, p.posicao, t); return page.mouse.move(pt.x, pt.y, { steps: 4 }); }
  if (p.clicar && p.posicao) { const pt = await pontoEm(page, p.clicar, p.posicao, t); return page.mouse.click(pt.x, pt.y); }
  if (p.clicar) return page.click(p.clicar, { timeout: t });
  if (p.enviarArquivo) return page.setInputFiles(p.enviarArquivo, [].concat(p.arquivo).map(a => path.resolve(a)), { timeout: t });
  if (p.arrastar) {
    const a = await pontoEm(page, p.arrastar, p.de, t);
    const bb = await page.locator(p.arrastar).first().boundingBox();
    const b = { x: bb.x + bb.width * p.ate[0], y: bb.y + bb.height * p.ate[1] };
    await page.mouse.move(a.x, a.y); await page.mouse.down();
    await page.mouse.move(b.x, b.y, { steps: 10 }); await page.mouse.up(); return;
  }
  if (p.baixar) {
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: t }), page.click(p.baixar, { timeout: t })]);
    let nome = `${String(fluxoIdx + 1).padStart(2, '0')}-${dl.suggestedFilename()}`.replace(/[^\w.-]/g, '_');
    for (let n = 2; capturas.includes(nome); n++) nome = nome.replace(/(-\d+)?(\.[^.]+)$/, `-${n}$2`); // vários downloads com o mesmo nome no fluxo
    const arq = path.join(dirSaida, nome);
    await dl.saveAs(arq);
    capturas.push(nome);
    if (p.validar) await validarDownload(page, spec, base, arq, p.validar);
    return;
  }
  if (p.verExpressao) {
    const deadline = Date.now() + t; let v;
    while (Date.now() < deadline) { v = await page.evaluate(p.verExpressao); if (v) return; await page.waitForTimeout(100); }
    throw new Error(`expressão falsa: ${p.verExpressao} (resultado: ${JSON.stringify(v)})`);
  }
  if (p.semRolagemHorizontal) {
    const r = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    if (r.sw > r.cw + 1) throw new Error(`rolagem horizontal: scrollWidth ${r.sw} > largura ${r.cw}`);
    return;
  }
  if (p.preencher) return page.fill(p.preencher, String(p.valor ?? ''), { timeout: t });
  if (p.tecla) return page.keyboard.press(p.tecla);
  if (p.recarregar) return page.reload();
  if (p.esperar) return page.waitForTimeout(p.esperar);
  if (p.verVisivel) return page.locator(p.verVisivel).first().waitFor({ state: 'visible', timeout: t });
  if (p.verTexto) {
    const loc = page.locator(p.verTexto).first();
    await loc.waitFor({ timeout: t });
    const deadline = Date.now() + t; let txt = '';
    while (Date.now() < deadline) { txt = await loc.innerText(); if (txt.includes(p.contem)) return; await page.waitForTimeout(100); }
    throw new Error(`"${p.verTexto}" não contém "${p.contem}" (texto: "${txt.slice(0, 120)}")`);
  }
  if (p.verQuantidade) {
    const deadline = Date.now() + t; let n = -1;
    while (Date.now() < deadline) { n = await page.locator(p.verQuantidade).count(); if (n === p.igual) return; await page.waitForTimeout(100); }
    throw new Error(`"${p.verQuantidade}": esperado ${p.igual}, encontrado ${n}`);
  }
  if (p.captura) {
    const nome = `${String(fluxoIdx + 1).padStart(2, '0')}-${p.captura}.png`.replace(/[^\w.-]/g, '_');
    await page.screenshot({ path: path.join(dirSaida, nome), fullPage: true });
    capturas.push(nome); return;
  }
  throw new Error(`Passo desconhecido: ${JSON.stringify(p)}`);
}

const arqSpec = process.argv[2];
if (!arqSpec) { console.error('Uso: node verificar.mjs <arquivo.json>'); process.exit(2); }
const spec = JSON.parse(await readFile(arqSpec, 'utf8'));
const dirSaida = path.resolve(path.dirname(new URL(import.meta.url).pathname), 'saida', spec.nome || 'app');
await rm(dirSaida, { recursive: true, force: true });
await mkdir(dirSaida, { recursive: true });

let srv, base = spec.urlBase;
if (spec.servirPasta) { srv = await servir(spec.servirPasta); base = `http://127.0.0.1:${srv.address().port}/`; }
if (!base) { console.error('Defina "servirPasta" ou "urlBase".'); process.exit(2); }

const browser = await chromium.launch();
const resultados = [];
for (const [i, fluxo] of spec.fluxos.entries()) {
  const ctx = await browser.newContext({ viewport: fluxo.viewport || { width: 1280, height: 800 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errosConsole = [], pedidosExternos = [];
  // semRedeExterna: toda requisição (inclusive de workers) precisa ir para o servidor local do app.
  ctx.on('request', r => { const u = r.url(); if (!/^(data:|blob:|about:)/.test(u) && !u.startsWith(new URL(base).origin)) pedidosExternos.push(u); });
  page.on('console', m => { if (m.type() === 'error') errosConsole.push(m.text()); });
  page.on('pageerror', e => errosConsole.push(String(e)));
  page.on('dialog', d => d.accept());
  const capturas = []; let erro = null, passoFalho = null;
  for (const [j, p] of fluxo.passos.entries()) {
    try { await executarPasso(page, p, base, dirSaida, i, capturas, spec); }
    catch (e) { erro = e.message.split('\n')[0]; passoFalho = j + 1; break; }
  }
  if (erro) { const nome = `${String(i + 1).padStart(2, '0')}-FALHA.png`; await page.screenshot({ path: path.join(dirSaida, nome), fullPage: true }).catch(() => {}); capturas.push(nome); }
  if (!erro && fluxo.semRedeExterna && pedidosExternos.length) erro = `Requisições para fora do app: ${pedidosExternos.slice(0, 3).join(' | ')}`;
  if (!erro && errosConsole.length) erro = `Erros no console: ${errosConsole.slice(0, 3).join(' | ')}`;
  resultados.push({ fluxo: fluxo.nome, ok: !erro, erro, passoFalho, capturas });
  console.log(`${erro ? '❌' : '✅'} ${fluxo.nome}${erro ? ` — passo ${passoFalho ?? '-'}: ${erro}` : ''}`);
  await ctx.close();
}
await browser.close(); srv?.close();

const ok = resultados.filter(r => r.ok).length;
const md = [`# Verificação de fluxos — ${spec.nome}`, '', `Data: ${new Date().toISOString()}`, `Resultado: **${ok}/${resultados.length}** fluxos passaram`, '',
  '| Fluxo | Status | Detalhe | Capturas |', '|---|---|---|---|',
  ...resultados.map(r => `| ${r.fluxo} | ${r.ok ? '✅' : '❌'} | ${r.erro ? `passo ${r.passoFalho ?? '-'}: ${r.erro.replace(/\|/g, '\\|')}` : ''} | ${r.capturas.join(', ')} |`)].join('\n');
await writeFile(path.join(dirSaida, 'relatorio.md'), md + '\n');
await writeFile(path.join(dirSaida, 'relatorio.json'), JSON.stringify(resultados, null, 2));
console.log(`\n${ok}/${resultados.length} fluxos passaram. Relatório: ${path.relative(process.cwd(), dirSaida)}/relatorio.md`);
process.exit(ok === resultados.length ? 0 : 1);
