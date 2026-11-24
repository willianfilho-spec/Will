// Controlador da interface: importação, edição, prévia e exportação.
import { A4, SECOES, TIPOS_BLOCO, QUADROS, blocoVazio, definirFontes, diagramar, desenharCanvas, desenharPdf } from './layout.js';
import { importarPdf, importarPptx } from './importar.js';

const { PDFDocument, StandardFonts } = window.PDFLib;
const $ = (s, el = document) => el.querySelector(s);
const ASSETS = { logo: new URL('../assets/logo60_sm.png', import.meta.url).href, logoCapa: new URL('../assets/logo60.png', import.meta.url).href };
const PADRAO = { cabecalho: 'GUIA SIGAA', rodapeEsq: 'DIOAC | PROEN | UFMA', rodapeMeio: '(SIGAA, 2026)', rodapeRot: 'Sumário' };

let doc = { ...PADRAO, paginas: [] };
let sel = 0;
const imagens = new Map();

// ---------------------------------------------------------------- utilidades
function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k in e && typeof v !== 'string') e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const f of filhos.flat()) if (f != null && f !== false) e.append(f instanceof Node ? f : document.createTextNode(f));
  return e;
}
function status(msg) { const s = $('#status'); s.textContent = msg || ''; s.classList.toggle('on', !!msg); }
function erro(msg) { $('#erro span').textContent = msg; $('#erro').classList.add('on'); }
$('#fechaErro').onclick = () => $('#erro').classList.remove('on');
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function imagem(src) {
  const chave = ASSETS[src] || src;
  if (imagens.has(chave)) return imagens.get(chave);
  const im = new Image();
  im.src = chave;
  imagens.set(chave, null);
  im.decode().then(() => { imagens.set(chave, im); agendarPrevia(); }).catch(() => {});
  return null;
}
const mapaImagens = { get: (src) => imagem(src) };

// ---------------------------------------------------------------- persistência local (IndexedDB)
const IDB = 'padronizador-guia';
function idb() {
  return new Promise((ok, falha) => {
    const r = indexedDB.open(IDB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore('kv');
    r.onsuccess = () => ok(r.result); r.onerror = () => falha(r.error);
  });
}
async function gravarLocal() {
  try { const db = await idb(); db.transaction('kv', 'readwrite').objectStore('kv').put(JSON.stringify(doc), 'projeto'); } catch { /* sem armazenamento: segue sem autosave */ }
}
async function lerLocal() {
  try {
    const db = await idb();
    return await new Promise((ok) => { const r = db.transaction('kv').objectStore('kv').get('projeto'); r.onsuccess = () => ok(r.result ? JSON.parse(r.result) : null); r.onerror = () => ok(null); });
  } catch { return null; }
}
const autosave = debounce(gravarLocal, 800);

// ---------------------------------------------------------------- estado → tela
function alterou({ estrutura = false } = {}) {
  if (estrutura) { desenharLista(); desenharEditor(); }
  else atualizarItemLista();
  agendarPrevia();
  autosave();
  const tem = doc.paginas.length > 0;
  $('#salvar').disabled = !tem; $('#baixar').disabled = !tem;
  $('#app').classList.toggle('oculto', !tem);
  $('#vazio').classList.toggle('on', !tem);
}

function nomePagina(p) {
  if (p.tipo === 'capa') return 'Capa';
  if (p.tipo === 'original') return (p.titulo || 'Página') + ' (original)';
  return p.titulo || p.secao || (p.blocos?.[0]?.titulo || p.blocos?.[0]?.rotulo || 'Sem título');
}
function itemLista(p, i) {
  const n = (p.avisos || []).length;
  return el('div', { class: `pag${i === sel ? ' on' : ''}${p.oculta ? ' oculta' : ''}`, 'data-i': String(i), onclick: () => { sel = i; desenharLista(); desenharEditor(); agendarPrevia(); } },
    el('span', { class: 'n' }, String(i + 1)),
    el('span', { class: 't' }, nomePagina(p), el('small', {}, p.tipo === 'capa' ? 'capa' : p.secao || (p.tipo === 'original' ? 'mantida como no original' : '—'))),
    n ? el('span', { title: (p.avisos || []).join('\n') }, `⚠ ${n}`) : null,
    el('span', { class: `dot ${p.confianca || 'alta'}`, title: `Confiança da leitura automática: ${p.confianca || 'alta'}` }));
}
function desenharLista() {
  const l = $('#lista'); l.replaceChildren(...doc.paginas.map(itemLista));
  l.querySelector('.on')?.scrollIntoView({ block: 'nearest' });
}
function atualizarItemLista() {
  const atual = $(`#lista [data-i="${sel}"]`);
  if (atual && doc.paginas[sel]) atual.replaceWith(itemLista(doc.paginas[sel], sel));
}

// Campos ligados a um objeto: escrevem direto no estado.
function campo(rotulo, obj, chave, tipo = 'input', extra = {}) {
  const ctrl = tipo === 'textarea' ? el('textarea', extra) : tipo === 'select' ? el('select', {}, ...extra.opcoes.map(([v, t]) => el('option', { value: v }, t))) : el('input', extra);
  ctrl.value = obj[chave] ?? '';
  ctrl.addEventListener(tipo === 'select' ? 'change' : 'input', () => {
    let v = ctrl.value;
    if (extra.setas) { const pos = ctrl.selectionStart; const nv = v.replace(/\s*(->|=>|>)\s*/g, ' → '); if (nv !== v) { v = nv; ctrl.value = v; ctrl.selectionStart = ctrl.selectionEnd = Math.min(v.length, pos + 1); } }
    obj[chave] = v;
    alterou({ estrutura: !!extra.estrutura });
  });
  return el('label', { class: 'campo' }, rotulo, ctrl);
}

function editorItens(b, rotT, rotD) {
  const caixa = el('div');
  (b.itens || []).forEach((it, i) => {
    caixa.append(el('div', { class: 'item' },
      el('div', { class: 'ih' }, `Item ${i + 1}`, el('span', {},
        el('button', { class: 'btn pq', title: 'Subir', onclick: () => { if (i) { [b.itens[i - 1], b.itens[i]] = [b.itens[i], b.itens[i - 1]]; alterou({ estrutura: true }); } } }, '↑'), ' ',
        el('button', { class: 'btn pq perigo', title: 'Remover item', onclick: () => { b.itens.splice(i, 1); alterou({ estrutura: true }); } }, '✕'))),
      campo(rotT, it, 't'), campo(rotD, it, 'd', 'textarea', { rows: 2 })));
  });
  caixa.append(el('button', { class: 'btn pq', onclick: () => { (b.itens ||= []).push({ t: '', d: '' }); alterou({ estrutura: true }); } }, '+ Item'));
  return caixa;
}

function editorBloco(b, i, p) {
  const corpo = [];
  switch (b.tipo) {
    case 'caminho': {
      const proxy = { v: (b.linhas || []).join('\n') };
      const c = campo('Uma linha por caminho (digite > ou -> e vira →)', proxy, 'v', 'textarea', { rows: 2, setas: true });
      c.querySelector('textarea').addEventListener('input', () => { b.linhas = proxy.v.split('\n'); });
      corpo.push(c); break;
    }
    case 'passos':
      corpo.push(campo('Rótulo', b, 'rotulo'), editorItens(b, 'Ação (negrito)', 'Detalhe'));
      corpo.push(el('label', { class: 'chk' }, Object.assign(el('input', { type: 'checkbox', onchange: (e) => { b.largo = e.target.checked; alterou(); } }), { checked: !!b.largo }), 'Largura total (não pôr quadros ao lado)'));
      break;
    case 'quadro':
      corpo.push(el('div', { class: 'linha' },
        campo('Tipo', b, 'variante', 'select', { opcoes: Object.entries(QUADROS).map(([k, v]) => [k, v.rotulo[0] + v.rotulo.slice(1).toLowerCase()]) }),
        campo('Rótulo', b, 'rotulo')), campo('Texto', b, 'texto', 'textarea', { rows: 3 }));
      break;
    case 'cards':
      corpo.push(el('div', { class: 'linha' }, campo('Rótulo (opcional)', b, 'rotulo'),
        campo('Estilo', b, 'estilo', 'select', { opcoes: [['lateral', 'Barra lateral'], ['topo', 'Barra no topo']] })),
      editorItens(b, 'Título do cartão', 'Texto (linhas com • viram lista)'));
      break;
    case 'imagem': {
      const fi = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif' });
      fi.onchange = async () => {
        const f = fi.files[0]; if (!f) return;
        const bmp = await createImageBitmap(f);
        const cv = el('canvas', { width: bmp.width, height: bmp.height }); cv.getContext('2d').drawImage(bmp, 0, 0);
        Object.assign(b, { src: f.type === 'image/jpeg' ? await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(f); }) : cv.toDataURL('image/png'), iw: bmp.width, ih: bmp.height });
        alterou({ estrutura: true });
      };
      corpo.push(b.src ? el('img', { class: 'thumb', src: b.src, alt: 'Imagem do bloco' }) : el('p', { class: 'hint' }, 'Sem imagem.'),
        el('label', { class: 'campo' }, 'Trocar imagem', fi), el('div', { class: 'linha' }, campo('Rótulo', b, 'rotulo'), campo('Legenda', b, 'legenda')));
      break;
    }
    case 'tabela': {
      const proxy = { v: (b.linhas || []).map((l) => l.join(' | ')).join('\n') };
      const c = campo('Uma linha por linha da tabela; separe as células com | (a 1ª linha é o cabeçalho)', proxy, 'v', 'textarea', { rows: 4 });
      c.querySelector('textarea').addEventListener('input', () => { b.linhas = proxy.v.split('\n').map((l) => l.split('|').map((s) => s.trim())); });
      corpo.push(campo('Rótulo (opcional)', b, 'rotulo'), c);
      break;
    }
    default:
      corpo.push(el('div', { class: 'linha' }, campo('Rótulo (opcional)', b, 'rotulo'), campo('Título (opcional)', b, 'titulo')),
        campo('Texto (linhas com •, - ou 1. viram lista)', b, 'texto', 'textarea', { rows: 4 }));
  }
  const mover = (d) => { const j = i + d; if (j < 0 || j >= p.blocos.length) return; [p.blocos[i], p.blocos[j]] = [p.blocos[j], p.blocos[i]]; alterou({ estrutura: true }); };
  return el('div', { class: 'bloco' },
    el('div', { class: 'bh' }, TIPOS_BLOCO[b.tipo] || b.tipo, el('span', { class: 'sp' }),
      el('button', { class: 'btn pq', title: 'Subir', onclick: () => mover(-1) }, '↑'),
      el('button', { class: 'btn pq', title: 'Descer', onclick: () => mover(1) }, '↓'),
      el('button', { class: 'btn pq', title: 'Duplicar', onclick: () => { p.blocos.splice(i + 1, 0, structuredClone(b)); alterou({ estrutura: true }); } }, '⧉'),
      el('button', { class: 'btn pq perigo', title: 'Excluir bloco', onclick: () => { p.blocos.splice(i, 1); alterou({ estrutura: true }); } }, '✕')),
    ...corpo);
}

function desenharEditor() {
  const ed = $('#editor');
  const p = doc.paginas[sel];
  if (!p) { ed.replaceChildren(); return; }
  const tipos = [['conteudo', 'Conteúdo padronizado'], ['capa', 'Capa']];
  if (p.original) tipos.push(['original', 'Manter como no original']);
  const partes = [
    el('div', { class: 'linha' }, el('h2', {}, `Página ${sel + 1}`), el('span', { class: 'sp' }),
      el('button', { class: 'btn pq', title: 'Subir página', onclick: () => moverPagina(-1) }, '↑'),
      el('button', { class: 'btn pq', title: 'Descer página', onclick: () => moverPagina(1) }, '↓'),
      el('button', { class: 'btn pq', title: 'Duplicar página', onclick: () => { doc.paginas.splice(sel + 1, 0, structuredClone(p)); sel++; alterou({ estrutura: true }); } }, '⧉'),
      el('button', { class: 'btn pq perigo', onclick: () => { if (confirm('Excluir esta página?')) { doc.paginas.splice(sel, 1); sel = Math.max(0, sel - 1); alterou({ estrutura: true }); } } }, 'Excluir')),
  ];
  if (p.avisos?.length) partes.push(el('div', { class: 'avisos' }, el('b', {}, 'Pontos a conferir na leitura automática'), el('ul', {}, ...p.avisos.map((a) => el('li', {}, a))),
    el('button', { class: 'btn pq', onclick: () => { p.avisos = []; alterou({ estrutura: true }); } }, 'Marcar como conferido')));
  partes.push(el('div', { class: 'linha' }, campo('Tipo de página', p, 'tipo', 'select', { opcoes: tipos, estrutura: true }),
    el('label', { class: 'chk' }, Object.assign(el('input', { type: 'checkbox', onchange: (e) => { p.oculta = e.target.checked; alterou(); } }), { checked: !!p.oculta }), 'Não incluir no PDF')));
  if (p.tipo === 'capa') {
    partes.push(campo('Rótulo superior', p, 'guia'), campo('Subtítulo (faixa dourada)', p, 'subtitulo'), campo('Descrição', p, 'descricao', 'textarea', { rows: 2 }), campo('Rodapé (uma linha por linha)', p, 'rodape', 'textarea', { rows: 2 }));
  } else if (p.tipo === 'original') {
    partes.push(el('p', { class: 'hint' }, 'Esta página entra no PDF exatamente como estava no arquivo importado (como imagem). Use só quando a leitura automática não for aproveitável.'));
  } else {
    const dl = el('datalist', { id: 'secoes' }, ...SECOES.map((s) => el('option', { value: s.nome })), ...SECOES.map((s) => el('option', { value: 'FAQ | ' + s.nome })));
    const cSec = campo('Seção (define a cor)', p, 'secao', 'input', { list: 'secoes' });
    partes.push(dl, el('div', { class: 'linha' }, cSec, campo('Nº do FAQ (ex.: 15 ou FAQ 07, FAQ 08)', p, 'faq')),
      campo(p.secao ? 'Título do procedimento' : 'Título da página (sem seção vira título grande)', p, 'titulo'),
      campo('Alinhamento do texto', p, 'alinhamento', 'select', { opcoes: [['esquerda', 'À esquerda'], ['centro', 'Centralizado']] }));
    (p.blocos ||= []).forEach((b, i) => partes.push(editorBloco(b, i, p)));
    const sTipo = el('select', {}, ...Object.entries(TIPOS_BLOCO).map(([k, v]) => el('option', { value: k }, v)));
    partes.push(el('div', { class: 'add' }, sTipo, el('button', { class: 'btn', onclick: () => { p.blocos.push(blocoVazio(sTipo.value)); alterou({ estrutura: true }); } }, '+ Adicionar bloco')));
  }
  ed.replaceChildren(...partes);
}

function moverPagina(d) {
  const j = sel + d; if (j < 0 || j >= doc.paginas.length) return;
  [doc.paginas[sel], doc.paginas[j]] = [doc.paginas[j], doc.paginas[sel]]; sel = j; alterou({ estrutura: true });
}

// ---------------------------------------------------------------- prévia
let quadro = 0;
function agendarPrevia() { cancelAnimationFrame(quadro); quadro = requestAnimationFrame(desenharPrevia); }
function canvasFolha(cmds) {
  const dpr = Math.min(2, window.devicePixelRatio || 1) * 1.15;
  const cv = el('canvas', { class: 'folha', width: Math.round(A4.w * dpr), height: Math.round(A4.h * dpr) });
  const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  desenharCanvas(ctx, cmds, mapaImagens);
  return cv;
}
function desenharPrevia() {
  const box = $('#folhas');
  const p = doc.paginas[sel];
  if (!p) { box.replaceChildren(); return; }
  const saida = diagramar(doc);
  const minhas = saida.map((s, i) => ({ ...s, n: i + 1 })).filter((s) => s.origem === sel);
  const comparar = $('#comparar').checked && p.original;
  $('#infoPrevia').textContent = minhas.length ? `Gera ${minhas.length > 1 ? `as páginas ${minhas[0].n}–${minhas[minhas.length - 1].n}` : `a página ${minhas[0].n}`} do PDF final (${saida.length} no total)` : 'Página não incluída no PDF';
  const filhos = [];
  minhas.forEach((s, k) => {
    const folha = canvasFolha(s.cmds);
    folha.setAttribute('aria-label', `Prévia da página ${s.n}`);
    if (comparar && k === 0) {
      filhos.push(el('div', { class: 'par' }, Object.assign(el('img', { class: 'folha', alt: 'Original' }), { src: p.original }), folha));
      filhos.push(el('div', { class: 'rot-folha' }, 'Original  ·  Padronizada'));
    } else filhos.push(folha);
    if (s.avisos.length) filhos.push(el('div', { class: 'avisos' }, s.avisos.join(' ')));
  });
  box.replaceChildren(...filhos);
}
$('#comparar').onchange = agendarPrevia;

// ---------------------------------------------------------------- importar / exportar
async function importarArquivo(f) {
  if (!f) return;
  const nome = f.name.toLowerCase();
  const ehPdf = nome.endsWith('.pdf') || f.type === 'application/pdf';
  const ehPptx = nome.endsWith('.pptx');
  if (!ehPdf && !ehPptx) { erro('Formato não suportado. Envie um arquivo .pdf ou .pptx (o formato antigo .ppt não é lido: salve-o como .pptx).'); return; }
  try {
    status(`Lendo ${f.name}…`);
    const buf = await f.arrayBuffer();
    const prog = (n, t) => status(`Lendo ${f.name}: página ${n} de ${t}…`);
    const pags = ehPdf ? await importarPdf(buf, prog) : await importarPptx(buf, prog);
    if (!pags.length) throw new Error('Nenhuma página encontrada.');
    let anexar = false;
    if (doc.paginas.length) anexar = !confirm(`Substituir o projeto atual pelas ${pags.length} páginas de "${f.name}"?\n\nOK = substituir · Cancelar = acrescentar ao final`);
    if (!anexar) { doc = { ...PADRAO, ...doc, paginas: [] }; sel = 0; } else sel = doc.paginas.length;
    doc.paginas.push(...pags);
    doc.origem = f.name;
    const conferir = pags.filter((p) => p.avisos?.length).length;
    status(`${pags.length} páginas importadas de ${f.name}. ${conferir ? `${conferir} com pontos a conferir (⚠ na lista).` : 'Nenhum ponto de atenção.'}`);
    setTimeout(() => status(''), 7000);
    preencherCfg();
    alterou({ estrutura: true });
  } catch (e) {
    console.error(e); status('');
    erro(`Não foi possível ler "${f.name}": ${e.message || e}`);
  }
}

async function bytesDe(src) { return new Uint8Array(await (await fetch(ASSETS[src] || src)).arrayBuffer()); }

async function exportarPdf() {
  const btn = $('#baixar'); btn.disabled = true;
  try {
    status('Gerando PDF padronizado…');
    const saida = diagramar(doc);
    const pdf = await PDFDocument.create();
    const fontes = { reg: await pdf.embedFont(StandardFonts.Helvetica), bold: await pdf.embedFont(StandardFonts.HelveticaBold) };
    const emb = new Map();
    for (const s of saida) for (const k of s.cmds) {
      if (k.k !== 'img' || emb.has(k.src)) continue;
      const bytes = await bytesDe(k.src);
      const jpg = bytes[0] === 0xff && bytes[1] === 0xd8;
      emb.set(k.src, jpg ? await pdf.embedJpg(bytes) : await pdf.embedPng(bytes));
    }
    for (const s of saida) desenharPdf(pdf.addPage([A4.w, A4.h]), s.cmds, emb, fontes);
    pdf.setTitle(`${doc.cabecalho || 'Guia SIGAA'} — versão padronizada`);
    pdf.setProducer('Padronizador do Guia SIGAA');
    const blob = new Blob([await pdf.save()], { type: 'application/pdf' });
    const base = (doc.origem || 'guia-sigaa').replace(/\.(pdf|pptx)$/i, '');
    const a = el('a', { href: URL.createObjectURL(blob), download: `${base}-padronizado.pdf` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    status(`PDF gerado: ${saida.length} páginas.`); setTimeout(() => status(''), 5000);
  } catch (e) { console.error(e); status(''); erro('Falha ao gerar o PDF: ' + (e.message || e)); }
  finally { btn.disabled = false; }
}

function preencherCfg() { document.querySelectorAll('[data-doc]').forEach((i) => { i.value = doc[i.dataset.doc] ?? ''; }); }
document.querySelectorAll('[data-doc]').forEach((i) => i.addEventListener('input', () => { doc[i.dataset.doc] = i.value; alterou(); }));

$('#arquivo').onchange = (e) => { importarArquivo(e.target.files[0]); e.target.value = ''; };
$('#arquivo2').onchange = (e) => { importarArquivo(e.target.files[0]); e.target.value = ''; };
$('#projeto').onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (!Array.isArray(d.paginas)) throw new Error('arquivo não é um projeto do padronizador');
    doc = { ...PADRAO, ...d }; sel = 0; preencherCfg(); alterou({ estrutura: true });
  } catch (err) { erro('Projeto inválido: ' + err.message); }
};
$('#salvar').onclick = () => {
  const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(doc)], { type: 'application/json' })), download: (doc.origem || 'guia').replace(/\.(pdf|pptx)$/i, '') + '-projeto.json' });
  document.body.append(a); a.click(); a.remove();
};
$('#novo').onclick = () => { if (!doc.paginas.length || confirm('Descartar o projeto atual?')) { doc = { ...PADRAO, paginas: [] }; sel = 0; preencherCfg(); alterou({ estrutura: true }); } };
$('#baixar').onclick = exportarPdf;
$('#addPag').onclick = () => { doc.paginas.splice(sel + 1, 0, { tipo: 'conteudo', secao: '', titulo: 'Nova página', faq: '', blocos: [blocoVazio('caminho'), blocoVazio('passos')], avisos: [], confianca: 'alta' }); sel++; alterou({ estrutura: true }); };

// Arrastar e soltar em qualquer lugar da janela.
addEventListener('dragover', (e) => { e.preventDefault(); document.body.classList.add('arrastando'); });
addEventListener('dragleave', (e) => { if (!e.relatedTarget) document.body.classList.remove('arrastando'); });
addEventListener('drop', (e) => { e.preventDefault(); document.body.classList.remove('arrastando'); importarArquivo(e.dataTransfer.files[0]); });

// ---------------------------------------------------------------- início
(async () => {
  const medidor = await PDFDocument.create();
  definirFontes({ reg: await medidor.embedFont(StandardFonts.Helvetica), bold: await medidor.embedFont(StandardFonts.HelveticaBold) });
  const salvo = await lerLocal();
  if (salvo?.paginas?.length) { doc = { ...PADRAO, ...salvo }; status('Projeto anterior recuperado deste navegador.'); setTimeout(() => status(''), 4000); }
  preencherCfg();
  alterou({ estrutura: true });
  window.__padronizador = { get doc() { return doc; }, diagramar: () => diagramar(doc), exportarPdf };
})();
