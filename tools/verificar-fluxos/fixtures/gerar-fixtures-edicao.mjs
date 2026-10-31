#!/usr/bin/env node
// Gera as fixtures do "Editar texto":
//   edicao-camada-texto.pdf  (A): fundo creme + faixa vinho com texto branco, COM camada de texto.
//   edicao-so-imagem.pdf     (B): cartaz estilo UFMA em que o texto faz parte da imagem (SEM camada de texto).
// Uso: node tools/verificar-fluxos/fixtures/gerar-fixtures-edicao.mjs
// Usa o pdf-lib vendorizado e o Chromium do Playwright (para rasterizar a imagem da fixture B).
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const aqui = path.dirname(new URL(import.meta.url).pathname);
const require = createRequire(import.meta.url);
const { PDFDocument, StandardFonts, rgb } = require(path.resolve(aqui, '../../../editor-pdf/vendor/pdf-lib/pdf-lib.min.js'));
const { chromium } = require('playwright');
const W = 595.28, H = 841.89;
const hex = h => rgb(...[1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255));

// ---- A: com camada de texto ----
{
  const doc = await PDFDocument.create();
  const pg = doc.addPage([W, H]);
  const reg = await doc.embedFont(StandardFonts.Helvetica), neg = await doc.embedFont(StandardFonts.HelveticaBold);
  pg.drawRectangle({ x: 0, y: 0, width: W, height: H, color: hex('#F4EAD5') });
  pg.drawRectangle({ x: 0, y: H - 330, width: W, height: 110, color: hex('#7A1238') });
  pg.drawText('Comunicado da Coordenacao', { x: 50, y: H - 120, size: 26, font: neg, color: hex('#2B1A20') });
  pg.drawText('Codigo do item: BETA-2024-XYZ', { x: 50, y: H - 285, size: 30, font: neg, color: hex('#FFFFFF') });
  pg.drawText('Prazo final: 30/11/2026, sem prorrogacao.', { x: 50, y: H - 420, size: 16, font: reg, color: hex('#2B1A20') });
  await writeFile(path.join(aqui, 'edicao-camada-texto.pdf'), await doc.save());
}

// ---- B: só imagem (cartaz) ----
{
  const navegador = await chromium.launch();
  const pagina = await navegador.newPage({ viewport: { width: 600, height: 600 } });
  const woff = async n => (await readFile(path.resolve(aqui, '../../../editor-pdf/vendor/fontes', n))).toString('base64');
  await pagina.addStyleTag({ content: `
    @font-face{font-family:NS;font-weight:700;src:url(data:font/woff;base64,${await woff('noto-sans-latin-700-normal.woff')})}
    @font-face{font-family:NS;font-weight:400;src:url(data:font/woff;base64,${await woff('noto-sans-latin-400-normal.woff')})}` });
  const dataUrl = await pagina.evaluate(async () => {
    await document.fonts.load('700 100px NS'); await document.fonts.load('400 50px NS');
    const c = document.createElement('canvas'); c.width = 1240; c.height = 1754;
    const x = c.getContext('2d');
    let g = x.createLinearGradient(0, 0, 0, 1754); g.addColorStop(0, '#F8F0DF'); g.addColorStop(1, '#EBDDBE');
    x.fillStyle = g; x.fillRect(0, 0, 1240, 1754);
    g = x.createLinearGradient(0, 560, 0, 800); g.addColorStop(0, '#8A1640'); g.addColorStop(1, '#5E0E2B');
    x.fillStyle = g; x.fillRect(0, 560, 1240, 240);
    x.fillStyle = '#DDA544'; x.fillRect(0, 800, 1240, 14);
    x.textAlign = 'center'; x.textBaseline = 'alphabetic';
    x.fillStyle = '#FFFFFF'; x.font = '700 112px NS'; x.fillText('ATENÇÃO, DISCENTE!', 620, 718);
    x.fillStyle = '#2B1A20'; x.font = '400 54px NS'; x.fillText('Matrículas abertas até 30 de novembro', 620, 930);
    x.font = '700 70px NS'; x.fillStyle = '#7A1238'; x.fillText('Universidade Federal do Maranhão', 620, 330);
    return c.toDataURL('image/png');
  });
  await navegador.close();
  const png = Buffer.from(dataUrl.split(',')[1], 'base64');
  const doc = await PDFDocument.create();
  const pg = doc.addPage([W, H]);
  const img = await doc.embedPng(png);
  pg.drawImage(img, { x: 0, y: 0, width: W, height: H });
  await writeFile(path.join(aqui, 'edicao-so-imagem.pdf'), await doc.save());
}
console.log('Fixtures geradas em', aqui);
