// Leitor mínimo de ZIP (suficiente para PPTX): lê o diretório central e
// descompacta entradas "deflate" com DecompressionStream, nativo do navegador.
export async function abrirZip(buffer) {
  const dv = new DataView(buffer);
  let eocd = -1;
  for (let i = buffer.byteLength - 22; i >= Math.max(0, buffer.byteLength - 65557); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('Arquivo não é um ZIP/PPTX válido.');
  const total = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const entradas = new Map();
  const dec = new TextDecoder();
  for (let n = 0; n < total; n++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error('Diretório do ZIP corrompido.');
    const metodo = dv.getUint16(p + 10, true), tam = dv.getUint32(p + 20, true);
    const ln = dv.getUint16(p + 28, true), le = dv.getUint16(p + 30, true), lc = dv.getUint16(p + 32, true);
    const local = dv.getUint32(p + 42, true);
    const nome = dec.decode(new Uint8Array(buffer, p + 46, ln));
    entradas.set(nome, { metodo, tam, local });
    p += 46 + ln + le + lc;
  }
  async function bytes(nome) {
    const e = entradas.get(nome);
    if (!e) return null;
    const ln = dv.getUint16(e.local + 26, true), le = dv.getUint16(e.local + 28, true);
    const ini = e.local + 30 + ln + le;
    const dados = new Uint8Array(buffer, ini, e.tam);
    if (e.metodo === 0) return dados.slice();
    if (e.metodo !== 8) throw new Error(`Compressão ZIP não suportada (${e.metodo}).`);
    const ds = new Blob([dados]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(ds).arrayBuffer());
  }
  return {
    nomes: () => [...entradas.keys()],
    bytes,
    texto: async (nome) => { const b = await bytes(nome); return b ? new TextDecoder().decode(b) : null; },
  };
}
