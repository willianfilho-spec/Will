// Extração de conteúdo com pdf.js: texto, imagens embutidas e página como PNG.

/** Texto da página, com quebras de linha reconstruídas a partir das posições. */
export async function textoDaPagina(page) {
  const tc = await page.getTextContent();
  let out = '', yAnterior = null;
  for (const it of tc.items) {
    if (!('str' in it)) continue;
    const y = it.transform[5];
    if (yAnterior !== null && Math.abs(y - yAnterior) > Math.max(2, (it.height || 10) * 0.5) && !out.endsWith('\n')) out += '\n';
    out += it.str;
    if (it.hasEOL) out += '\n';
    if (it.str) yAnterior = y;
  }
  return out.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}

const obter = (objs, id) => new Promise(ok => objs.get(id, ok));

// Converte o objeto de imagem do pdf.js (ImageBitmap ou pixels crus) em canvas.
function imagemParaCanvas(img) {
  const { width: w, height: h } = img;
  const c = Object.assign(document.createElement('canvas'), { width: w, height: h });
  const ctx = c.getContext('2d');
  if (img.bitmap) { ctx.drawImage(img.bitmap, 0, 0); return c; }
  if (!img.data) return null;
  const rgba = new Uint8ClampedArray(w * h * 4);
  const d = img.data;
  if (img.kind === 3) rgba.set(d.subarray(0, rgba.length)); // RGBA_32BPP
  else if (img.kind === 2) { // RGB_24BPP
    for (let i = 0, j = 0; j < rgba.length; i += 3, j += 4) { rgba[j] = d[i]; rgba[j + 1] = d[i + 1]; rgba[j + 2] = d[i + 2]; rgba[j + 3] = 255; }
  } else if (img.kind === 1) { // GRAYSCALE_1BPP (1 bit por pixel, linhas alinhadas a byte)
    const porLinha = (w + 7) >> 3;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const v = (d[y * porLinha + (x >> 3)] >> (7 - (x & 7))) & 1 ? 255 : 0;
      const j = (y * w + x) * 4; rgba[j] = rgba[j + 1] = rgba[j + 2] = v; rgba[j + 3] = 255;
    }
  } else return null;
  ctx.putImageData(new ImageData(rgba, w, h), 0, 0);
  return c;
}

/**
 * Imagens embutidas desenhadas na página (XObjects de imagem e imagens inline).
 * Os pixels são decodificados pelo pdf.js e regravados como PNG — não é o arquivo original
 * (um JPEG embutido sai como PNG, sem perda adicional mas maior).
 */
export async function imagensDaPagina(page, OPS) {
  const ops = await page.getOperatorList();
  const vistos = new Set(), saida = [];
  for (let i = 0; i < ops.fnArray.length; i++) {
    const fn = ops.fnArray[i], args = ops.argsArray[i];
    let img = null;
    if (fn === OPS.paintImageXObject || fn === OPS.paintImageXObjectRepeat) {
      const id = args[0];
      if (vistos.has(id)) continue; vistos.add(id);
      img = await obter(id.startsWith('g_') ? page.commonObjs : page.objs, id);
    } else if (fn === OPS.paintInlineImageXObject) {
      img = args[0];
    } else continue;
    if (!img) continue;
    const c = imagemParaCanvas(img);
    if (!c) continue;
    saida.push({ url: c.toDataURL('image/png'), largura: img.width, altura: img.height });
  }
  return saida;
}

/**
 * Renderiza a página (pdf.js) com as anotações do usuário por cima e devolve o canvas.
 * `css` entra no SVG das anotações (fontes embutidas em base64: um SVG desenhado como imagem não enxerga os arquivos da página).
 */
export async function paginaComoCanvas(page, anotacoes, info, elementoAnotacao, escala = 2, css = '') {
  const vp = page.getViewport({ scale: escala });
  const c = Object.assign(document.createElement('canvas'), { width: Math.floor(vp.width), height: Math.floor(vp.height) });
  const ctx = c.getContext('2d');
  await page.render({ canvasContext: ctx, canvas: c, viewport: vp }).promise;
  if (anotacoes.length) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    svg.setAttribute('viewBox', `0 0 ${info.w} ${info.h}`);
    svg.setAttribute('width', c.width); svg.setAttribute('height', c.height);
    if (css) { const st = document.createElementNS('http://www.w3.org/2000/svg', 'style'); st.textContent = css; svg.append(st); }
    for (const a of anotacoes) {
      const g = elementoAnotacao(a);
      g.querySelectorAll('.realce').forEach(r => r.setAttribute('style', 'mix-blend-mode:multiply'));
      svg.append(g);
    }
    const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(svg));
    const im = new Image();
    await new Promise((ok, erro) => { im.onload = ok; im.onerror = erro; im.src = url; });
    await im.decode?.().catch(() => {});
    ctx.drawImage(im, 0, 0, c.width, c.height);
  }
  return c;
}

/** Página inteira (com as anotações) em PNG a 2x (≈144 dpi). */
export async function paginaComoPng(page, anotacoes, info, elementoAnotacao, css = '') {
  return (await paginaComoCanvas(page, anotacoes, info, elementoAnotacao, 2, css)).toDataURL('image/png');
}

/** Página inteira (com as anotações) em JPEG, para substituir a página original no PDF. */
export async function paginaComoJpeg(page, anotacoes, info, elementoAnotacao, css, escala, qualidade = 0.92) {
  const c = await paginaComoCanvas(page, anotacoes, info, elementoAnotacao, escala, css);
  const blob = await new Promise(ok => c.toBlob(ok, 'image/jpeg', qualidade));
  c.width = c.height = 0;
  return new Uint8Array(await blob.arrayBuffer());
}
