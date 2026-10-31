#!/usr/bin/env node
// Gera o PDF de teste usado pelos fluxos do editor-pdf (conteúdo conhecido).
// Uso: node tools/verificar-fluxos/fixtures/gerar-pdf-teste.mjs
// Usa a cópia vendorizada do pdf-lib (editor-pdf/vendor), sem npm install.
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';
import zlib from 'node:zlib';
import path from 'node:path';

const aqui = path.dirname(new URL(import.meta.url).pathname);
const require = createRequire(import.meta.url);
const { PDFDocument, StandardFonts, rgb } = require(path.resolve(aqui, '../../../editor-pdf/vendor/pdf-lib/pdf-lib.min.js'));

// PNG 120x80 em degradê com um quadrado central, gerado sem dependências.
function png(w, h) {
  const linhas = [];
  for (let y = 0; y < h; y++) {
    const l = Buffer.alloc(1 + w * 3);
    for (let x = 0; x < w; x++) {
      const dentro = x > w / 3 && x < 2 * w / 3 && y > h / 4 && y < 3 * h / 4;
      l[1 + x * 3] = dentro ? 250 : Math.round(40 + 180 * x / w);
      l[2 + x * 3] = dentro ? 200 : Math.round(90 + 120 * y / h);
      l[3 + x * 3] = dentro ? 30 : 160;
    }
    linhas.push(l);
  }
  const chunk = (tipo, dados) => {
    const t = Buffer.from(tipo, 'ascii');
    const len = Buffer.alloc(4); len.writeUInt32BE(dados.length);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(zlib.crc32(Buffer.concat([t, dados])));
    return Buffer.concat([len, t, dados, crc]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(linhas))), chunk('IEND', Buffer.alloc(0))]);
}

const doc = await PDFDocument.create();
doc.setTitle('Documento de teste do Editor PDF');
const f = await doc.embedFont(StandardFonts.Helvetica);
const fb = await doc.embedFont(StandardFonts.HelveticaBold);
const paginas = [
  ['Pagina 1 - Relatorio Alfa', ['Frase conhecida: o rato roeu a roupa do rei de Roma.', 'Linha extra da primeira pagina para teste de extracao.']],
  ['Pagina 2 - Inventario Beta', ['Codigo do item: BETA-2024-XYZ.', 'Quantidade em estoque: 42 unidades.']],
  ['Pagina 3 - Imagem Gama', ['Abaixo, uma imagem embutida para teste.']],
];
for (const [i, [titulo, linhas]] of paginas.entries()) {
  const p = doc.addPage([595, 842]);
  p.drawText(titulo, { x: 60, y: 760, size: 24, font: fb, color: rgb(0.1, 0.1, 0.3) });
  linhas.forEach((l, k) => p.drawText(l, { x: 60, y: 710 - k * 24, size: 14, font: f }));
  p.drawText(`Rodape ${i + 1} de ${paginas.length}`, { x: 60, y: 40, size: 10, font: f, color: rgb(0.4, 0.4, 0.4) });
  if (i === 2) { const img = await doc.embedPng(png(120, 80)); p.drawImage(img, { x: 60, y: 420, width: 240, height: 160 }); }
}
const saida = path.join(aqui, 'documento-teste.pdf');
await writeFile(saida, await doc.save());
console.log('Gerado:', saida);
