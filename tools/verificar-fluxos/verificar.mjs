#!/usr/bin/env node
// Verificador de fluxos: executa no Chromium os passos de um arquivo JSON
// e gera relatório + capturas. Uso: node verificar.mjs <arquivo.json>
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };

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

async function executarPasso(page, p, base, dirSaida, fluxoIdx, capturas) {
  const t = 5000;
  if (p.ir !== undefined) return page.goto(new URL(p.ir, base).href);
  if (p.clicar) return page.click(p.clicar, { timeout: t });
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
await mkdir(dirSaida, { recursive: true });

let srv, base = spec.urlBase;
if (spec.servirPasta) { srv = await servir(spec.servirPasta); base = `http://127.0.0.1:${srv.address().port}/`; }
if (!base) { console.error('Defina "servirPasta" ou "urlBase".'); process.exit(2); }

const browser = await chromium.launch();
const resultados = [];
for (const [i, fluxo] of spec.fluxos.entries()) {
  const ctx = await browser.newContext({ viewport: fluxo.viewport || { width: 1280, height: 800 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errosConsole = [];
  page.on('console', m => { if (m.type() === 'error') errosConsole.push(m.text()); });
  page.on('pageerror', e => errosConsole.push(String(e)));
  page.on('dialog', d => d.accept());
  const capturas = []; let erro = null, passoFalho = null;
  for (const [j, p] of fluxo.passos.entries()) {
    try { await executarPasso(page, p, base, dirSaida, i, capturas); }
    catch (e) { erro = e.message.split('\n')[0]; passoFalho = j + 1; break; }
  }
  if (erro) { const nome = `${String(i + 1).padStart(2, '0')}-FALHA.png`; await page.screenshot({ path: path.join(dirSaida, nome), fullPage: true }).catch(() => {}); capturas.push(nome); }
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
