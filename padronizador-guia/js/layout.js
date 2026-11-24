// Modelo visual do Guia SIGAA e motor de diagramação.
// Medidas em pontos (1/72"), origem no canto superior esquerdo, A4 retrato.
// O motor gera uma "lista de desenho" (comandos simples) que é executada tanto
// pela prévia (canvas) quanto pela exportação (pdf-lib). Assim, prévia e PDF
// usam exatamente a mesma diagramação.

export const A4 = { w: 595.28, h: 841.89 };
export const M = 36;                 // margem lateral
export const CW = A4.w - 2 * M;      // largura útil
export const Y_MAX = 800;            // limite inferior do conteúdo (rodapé começa em 817)

// Cores medidas no manual de referência (Manual do Coordenador SIGAA 2026).
export const COR = {
  vinho: '#7A1238', rodape: '#5E0C2A', capa: '#600F2E', dourado: '#DDA544',
  teal: '#12A3A6', verde: '#2E7D59', vermelho: '#B33A4B', cinza: '#6B6B6B',
  texto: '#1A1A1A', corpo: '#333333', suave: '#666666', bege: '#F1ECE5',
  creme: '#FFF9EE', rosa: '#FDF0F0', linha: '#E4DCCF', branco: '#FFFFFF',
};

export const SECOES = [
  { nome: 'DADOS CADASTRAIS E COMUNICAÇÃO', cor: COR.vinho },
  { nome: 'REGULARIZAÇÃO ACADÊMICA', cor: COR.teal },
  { nome: 'TURMAS', cor: '#B8862B' },
  { nome: 'MATRÍCULAS', cor: COR.verde },
  { nome: 'ATIVIDADES', cor: COR.vermelho },
  { nome: 'CONSULTAS', cor: COR.cinza },
];
const CORES_CARD = [COR.vinho, COR.teal, COR.dourado, COR.verde, COR.vermelho, COR.cinza];

export const sem = (s) => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase().trim();
export function corDaSecao(secao) {
  const n = sem(secao).replace(/^FAQ\s*\|?\s*/, '');
  const s = SECOES.find((x) => n && (sem(x.nome) === n || sem(x.nome).startsWith(n) || n.startsWith(sem(x.nome))));
  return s ? s.cor : COR.vinho;
}

export const QUADROS = {
  observacao:     { rotulo: 'OBSERVAÇÃO',     fundo: COR.creme,  barra: COR.teal,     cor: COR.texto,    borda: '#EADFC8' },
  regulamentacao: { rotulo: 'REGULAMENTAÇÃO', fundo: COR.branco, barra: COR.teal,     cor: COR.vinho,    borda: COR.linha },
  atencao:        { rotulo: 'ATENÇÃO',        fundo: COR.rosa,   barra: COR.vermelho, cor: COR.vermelho, borda: '#F0D0D4' },
  destaque:       { rotulo: 'APRESENTAÇÃO',   fundo: COR.creme,  barra: COR.vinho,    cor: COR.vinho,    borda: '#EADFC8' },
};

export const TIPOS_BLOCO = {
  caminho: 'Caminho no SIGAA', passos: 'Passos (Como fazer)', quadro: 'Quadro (observação, norma, atenção)',
  cards: 'Cartões em grade', imagem: 'Imagem / tela do SIGAA', texto: 'Texto', tabela: 'Tabela',
};

export function blocoVazio(tipo) {
  switch (tipo) {
    case 'caminho': return { tipo, linhas: ['Menu → Opção'] };
    case 'passos': return { tipo, rotulo: 'COMO FAZER', itens: [{ t: 'Primeiro passo', d: '' }] };
    case 'quadro': return { tipo, variante: 'observacao', rotulo: 'OBSERVAÇÃO', texto: '' };
    case 'cards': return { tipo, rotulo: '', estilo: 'lateral', itens: [{ t: 'Título', d: '' }, { t: 'Título', d: '' }] };
    case 'imagem': return { tipo, rotulo: 'TELA DO SIGAA', src: '', iw: 0, ih: 0, legenda: 'Fonte: (SIGAA, 2026).' };
    case 'tabela': return { tipo, rotulo: '', linhas: [['Coluna 1', 'Coluna 2'], ['', '']] };
    default: return { tipo: 'texto', rotulo: '', titulo: '', texto: '' };
  }
}

// ---------------------------------------------------------------- texto
// A medição usa as métricas da Helvetica do pdf-lib (iguais às da Arial),
// para que a quebra de linha da prévia seja idêntica à do PDF.
let F = null; // { reg, bold } (PDFFont)
const okChar = new Map();
const TROCAS = { '≥': '>=', '≤': '<=', '≠': '!=', '✓': 'v', '✔': 'v', '►': '>', '▶': '>', '➔': '→', '⇒': '→', ' ': ' ', ' ': ' ', '​': '', '': '•', '': '•', '−': '-', '‐': '-', '…': '...' };

export function definirFontes(fontes) { F = fontes; okChar.clear(); }

export function limpar(s) {
  let out = '';
  for (const ch of String(s ?? '')) {
    if (ch === '→' || ch === '\n') { out += ch; continue; }
    const t = TROCAS[ch];
    if (t !== undefined) { out += t; continue; }
    if (!okChar.has(ch)) {
      let ok = true;
      try { F.reg.encodeText(ch); F.bold.encodeText(ch); } catch { ok = false; }
      okChar.set(ch, ok);
    }
    out += okChar.get(ch) ? ch : '?';
  }
  return out;
}

export function largura(s, size, bold) {
  const f = bold ? F.bold : F.reg;
  let w = 0;
  const partes = String(s).split('→');
  partes.forEach((p, i) => { if (p) w += f.widthOfTextAtSize(p, size); if (i < partes.length - 1) w += size * 1.05; });
  return w;
}

function quebrarPalavra(p, w, size, bold) {
  const pedacos = []; let cur = '';
  for (const ch of p) {
    if (cur && largura(cur + ch, size, bold) > w) { pedacos.push(cur); cur = ch; } else cur += ch;
  }
  if (cur) pedacos.push(cur);
  return pedacos;
}

// Devolve [{t, dx}] — dx é o recuo da linha (marcadores e listas numeradas).
export function quebrar(texto, w, size, bold = false) {
  const linhas = [];
  for (const par of limpar(texto).split('\n')) {
    const m = par.match(/^\s*((?:•|-|–|\d{1,2}[.)])\s+)/);
    let recuo = 0, corpo = par.trim();
    if (m) {
      const marca = m[1].trim().replace(/^[-–]$/, '•');
      corpo = marca + ' ' + par.slice(m[0].length).trim();
      recuo = largura(marca + ' ', size, bold);
    }
    if (!corpo) { linhas.push({ t: '', dx: 0 }); continue; }
    let atual = '', primeira = true;
    const flush = () => { linhas.push({ t: atual, dx: primeira ? 0 : recuo }); primeira = false; atual = ''; };
    for (const palavra of corpo.split(/\s+/)) {
      const lim = w - (primeira ? 0 : recuo);
      const tent = atual ? atual + ' ' + palavra : palavra;
      if (largura(tent, size, bold) <= lim) { atual = tent; continue; }
      if (atual) flush();
      const lim2 = w - (primeira ? 0 : recuo);
      if (largura(palavra, size, bold) > lim2) {
        const ps = quebrarPalavra(palavra, lim2, size, bold);
        ps.slice(0, -1).forEach((p) => { atual = p; flush(); });
        atual = ps[ps.length - 1];
      } else atual = palavra;
    }
    if (atual || primeira) flush();
  }
  return linhas;
}

// ---------------------------------------------------------------- comandos de desenho
const C = {
  rect: (x, y, w, h, o = {}) => ({ k: 'rect', x, y, w, h, ...o }),
  text: (t, x, y, size, bold, cor) => ({ k: 'text', t, x, y, size, bold, cor }),
  circ: (x, y, r, cor) => ({ k: 'circ', x, y, r, cor }),
  img: (src, x, y, w, h) => ({ k: 'img', src, x, y, w, h }),
  seta: (x, y, s, cor) => ({ k: 'seta', x, y, s, cor }),
};

// Texto numa linha, com setas desenhadas como vetor (a Helvetica padrão não tem "→").
function linhaTexto(cmds, t, x, y, size, bold, cor) {
  const partes = String(t).split('→');
  partes.forEach((p, i) => {
    if (p) { cmds.push(C.text(p, x, y, size, bold, cor)); x += largura(p, size, bold); }
    if (i < partes.length - 1) { cmds.push(C.seta(x + size * 0.12, y - size * 0.33, size * 0.8, cor)); x += size * 1.05; }
  });
}

function paragrafo(cmds, texto, x, y, w, size, bold, cor, lh, centro = false) {
  const ls = quebrar(texto, w, size, bold);
  ls.forEach((l, i) => {
    const xx = centro ? x + (w - largura(l.t, size, bold)) / 2 : x + l.dx;
    linhaTexto(cmds, l.t, xx, y + size + i * lh, size, bold, cor);
  });
  return ls.length * lh;
}
const alturaPar = (texto, w, size, bold, lh) => (texto ? quebrar(texto, w, size, bold).length * lh : 0);

// ---------------------------------------------------------------- blocos
// Cada medidor devolve { h, draw(x, y) => cmds[], dividir?(disp) => [a, b] | null }
const ROT = 9.5, CORPO = 9.5, LH = 13;

function rotulo(cmds, t, x, y, cor = COR.cinza) { if (!t) return 0; linhaTexto(cmds, limpar(t).toUpperCase(), x, y + ROT, ROT, true, cor); return 18; }
const altRotulo = (t) => (t ? 18 : 0);

function medirCaminho(b, w) {
  const lw = w - 140;
  const linhas = (b.linhas || []).filter((l) => l.trim());
  const ls = linhas.flatMap((l) => quebrar(l, lw, 10, true));
  const h = Math.max(30, ls.length * 14 + 16);
  return {
    h, draw(x, y) {
      const c = [C.rect(x, y, w, h, { fill: COR.bege, r: 4 })];
      linhaTexto(c, 'CAMINHO NO SIGAA', x + 14, y + h / 2 + 3.4, 9.5, true, COR.suave);
      ls.forEach((l, i) => linhaTexto(c, l.t, x + 130 + l.dx, y + (h - ls.length * 14) / 2 + 10.5 + i * 14, 10, true, COR.vinho));
      return c;
    },
  };
}

function medirPassos(b, w) {
  const tw = w - 26;
  const itens = (b.itens || []).map((it) => ({ ...it, ht: alturaPar(it.t, tw, 10, true, 13), hd: alturaPar(it.d, tw, CORPO, false, LH) }));
  const altItem = (it) => Math.max(16, it.ht + (it.d ? 3 + it.hd : 0));
  const montar = (lista, inicio, comRotulo) => {
    const h = (comRotulo ? altRotulo(b.rotulo) : 0) + lista.reduce((s, it) => s + altItem(it) + 10, 0) - (lista.length ? 10 : 0);
    return {
      h, draw(x, y) {
        const c = []; let yy = y + (comRotulo ? rotulo(c, b.rotulo, x, y) : 0);
        lista.forEach((it, i) => {
          const n = String(inicio + i + 1);
          c.push(C.circ(x + 8, yy + 7.5, 7.5, COR.vinho));
          linhaTexto(c, n, x + 8 - largura(n, 8, true) / 2, yy + 10.4, 8, true, COR.branco);
          paragrafo(c, it.t, x + 26, yy - 1.5, tw, 10, true, COR.texto, 13);
          if (it.d) paragrafo(c, it.d, x + 26, yy + it.ht + 1.5, tw, CORPO, false, COR.suave, LH);
          yy += altItem(it) + 10;
        });
        return c;
      },
      dividir(disp) {
        let acc = comRotulo ? altRotulo(b.rotulo) : 0, k = 0;
        while (k < lista.length && acc + altItem(lista[k]) <= disp) { acc += altItem(lista[k]) + 10; k++; }
        if (k === 0 || k === lista.length) return null;
        return [montar(lista.slice(0, k), inicio, comRotulo), montar(lista.slice(k), inicio + k, false)];
      },
    };
  };
  return montar(itens, 0, true);
}

function medirQuadro(b, w) {
  const v = QUADROS[b.variante] || QUADROS.observacao;
  const rot = b.rotulo ?? v.rotulo;
  const tw = w - 28;
  const ht = alturaPar(b.texto, tw, CORPO, false, LH);
  const h = 20 + (rot ? 16 : 0) + ht;
  return {
    h, draw(x, y) {
      const c = [C.rect(x, y, w, h, { fill: v.fundo, stroke: v.borda, lw: 0.6, r: 4 }), C.rect(x, y, 4, h, { fill: v.barra, r: 2 })];
      let yy = y + 10;
      if (rot) { linhaTexto(c, limpar(rot).toUpperCase(), x + 16, yy + 9.5, 9.5, true, v.cor); yy += 16; }
      paragrafo(c, b.texto, x + 16, yy - 1, tw, CORPO, false, '#444444', LH);
      return c;
    },
  };
}

function medirCards(b, w) {
  const gap = 12, cols = (b.itens || []).length === 1 ? 1 : 2, cw = (w - gap * (cols - 1)) / cols, tw = cw - 26;
  const topo = b.estilo === 'topo';
  const itens = (b.itens || []).map((it, i) => ({ ...it, i, ht: alturaPar(it.t, tw, 9.5, true, 12.5), hd: alturaPar(it.d, tw, CORPO, false, LH) }));
  const altCard = (it) => (topo ? 26 : 20) + it.ht + (it.d ? 4 + it.hd : 0);
  const linhas = [];
  for (let i = 0; i < itens.length; i += cols) linhas.push(itens.slice(i, i + cols));
  const altLinha = (l) => Math.max(...l.map(altCard));
  const montar = (ls, comRotulo) => {
    const h = (comRotulo ? altRotulo(b.rotulo) : 0) + ls.reduce((s, l) => s + altLinha(l) + gap, 0) - (ls.length ? gap : 0);
    return {
      h, draw(x, y) {
        const c = []; let yy = y + (comRotulo ? rotulo(c, b.rotulo, x, y) : 0);
        ls.forEach((l) => {
          const hl = altLinha(l);
          l.forEach((it, j) => {
            const cx = x + j * (cw + gap), cor = CORES_CARD[it.i % CORES_CARD.length];
            c.push(C.rect(cx, yy, cw, hl, { fill: COR.branco, stroke: COR.linha, lw: 0.6, r: 5 }));
            if (topo) c.push(C.rect(cx, yy, cw, 6, { fill: cor, r: 3 }));
            else c.push(C.rect(cx, yy, 4, hl, { fill: cor, r: 2 }));
            const y0 = yy + (topo ? 16 : 10);
            paragrafo(c, it.t, cx + 14, y0 - 1, tw, 9.5, true, topo ? cor : COR.texto, 12.5);
            if (it.d) paragrafo(c, it.d, cx + 14, y0 + it.ht + 3, tw, CORPO, false, COR.suave, LH);
          });
          yy += hl + gap;
        });
        return c;
      },
      dividir(disp) {
        let acc = comRotulo ? altRotulo(b.rotulo) : 0, k = 0;
        while (k < ls.length && acc + altLinha(ls[k]) <= disp) { acc += altLinha(ls[k]) + gap; k++; }
        if (k === 0 || k === ls.length) return null;
        return [montar(ls.slice(0, k), comRotulo), montar(ls.slice(k), false)];
      },
    };
  };
  return montar(linhas, true);
}

function medirImagem(b, w, maxH = 560) {
  const hr = altRotulo(b.rotulo), hl = b.legenda ? 16 : 0;
  const montar = (limite) => {
    let iw = w, ih = 120;
    if (b.src && b.iw && b.ih) { iw = Math.min(w, b.iw * 0.75 > 120 ? w : b.iw * 0.75); ih = (iw * b.ih) / b.iw; }
    if (ih > limite) { ih = limite; iw = b.iw ? (ih * b.iw) / b.ih : w; }
    const h = hr + 6 + ih + hl;
    return {
      h, ih, draw(x, y) {
        const c = []; let yy = y + rotulo(c, b.rotulo, x, y, COR.vinho) + 6;
        const ix = x + (w - iw) / 2;
        if (b.src) c.push(C.img(b.src, ix, yy, iw, ih));
        else { c.push(C.rect(ix, yy, iw, ih, { fill: '#F7F3EE', stroke: COR.linha, lw: 0.8, r: 3 })); linhaTexto(c, '[sem imagem]', ix + iw / 2 - 28, yy + ih / 2 + 3, 9, false, COR.suave); }
        c.push(C.rect(ix, yy, iw, ih, { stroke: COR.linha, lw: 0.6 }));
        if (b.legenda) linhaTexto(c, limpar(b.legenda), x, yy + ih + 13, 9, false, COR.corpo);
        return c;
      },
      // Imagem não se divide: encolhe até 60% da altura ideal; abaixo disso vai para a próxima página.
      encolher(disp) { const ideal = montar(maxH); const lim = disp - hr - 6 - hl; return lim >= Math.max(110, ideal.ih * 0.6) ? montar(lim) : null; },
    };
  };
  return montar(maxH);
}

function medirTexto(b, w, centro) {
  const ht = b.titulo ? alturaPar(b.titulo, w, 10.5, true, 14) + 4 : 0;
  const ls = quebrar(b.texto || '', w, 10, false);
  const montar = (linhas, comCab) => {
    const h = (comCab ? altRotulo(b.rotulo) + ht : 0) + linhas.length * 14;
    return {
      h, draw(x, y) {
        const c = []; let yy = y;
        if (comCab) { yy += rotulo(c, b.rotulo, x, y); if (b.titulo) { paragrafo(c, b.titulo, x, yy - 1, w, 10.5, true, COR.vinho, 14, centro); yy += ht; } }
        linhas.forEach((l, i) => {
          const xx = centro ? x + (w - largura(l.t, 10, false)) / 2 : x + l.dx;
          linhaTexto(c, l.t, xx, yy + 10 + i * 14, 10, false, COR.corpo);
        });
        return c;
      },
      dividir(disp) {
        const cab = comCab ? altRotulo(b.rotulo) + ht : 0;
        const k = Math.floor((disp - cab) / 14);
        if (k < 2 || k >= linhas.length) return null;
        return [montar(linhas.slice(0, k), comCab), montar(linhas.slice(k), false)];
      },
    };
  };
  return montar(b.texto ? ls : [], true);
}

function medirTabela(b, w) {
  const linhas = (b.linhas || []).filter((l) => l.some((c) => String(c).trim()));
  const nc = Math.max(1, ...linhas.map((l) => l.length));
  const cw = w / nc;
  const alt = linhas.map((l, i) => Math.max(...Array.from({ length: nc }, (_, j) => alturaPar(l[j] || ' ', cw - 12, 9, i === 0, 12))) + 10);
  const montar = (idx, comRotulo) => {
    const h = (comRotulo ? altRotulo(b.rotulo) : 0) + idx.reduce((s, i) => s + alt[i], 0);
    return {
      h, draw(x, y) {
        const c = []; let yy = y + (comRotulo ? rotulo(c, b.rotulo, x, y) : 0);
        idx.forEach((i, n) => {
          const cab = i === 0;
          c.push(C.rect(x, yy, w, alt[i], { fill: cab ? COR.vinho : n % 2 ? '#FBF8F4' : COR.branco, stroke: COR.linha, lw: 0.5 }));
          for (let j = 0; j < nc; j++) paragrafo(c, linhas[i][j] || '', x + j * cw + 6, yy + 3, cw - 12, 9, cab, cab ? COR.branco : COR.corpo, 12);
          yy += alt[i];
        });
        return c;
      },
      dividir(disp) {
        let acc = comRotulo ? altRotulo(b.rotulo) : 0, k = 0;
        while (k < idx.length && acc + alt[idx[k]] <= disp) { acc += alt[idx[k]]; k++; }
        if (k < 2 || k === idx.length) return null;
        return [montar(idx.slice(0, k), comRotulo), montar([0, ...idx.slice(k)], false)]; // repete o cabeçalho
      },
    };
  };
  return montar(linhas.map((_, i) => i), true);
}

export function medirBloco(b, w, centro) {
  switch (b.tipo) {
    case 'caminho': return medirCaminho(b, w);
    case 'passos': return medirPassos(b, w);
    case 'quadro': return medirQuadro(b, w);
    case 'cards': return medirCards(b, w);
    case 'imagem': return medirImagem(b, w);
    case 'tabela': return medirTabela(b, w);
    default: return medirTexto(b, w, centro);
  }
}

// Passos seguidos de quadros ficam lado a lado, como no modelo (passos à esquerda, quadros à direita).
function unidades(blocos) {
  const u = [];
  for (let i = 0; i < blocos.length; i++) {
    const b = blocos[i];
    if (b.tipo === 'passos' && blocos[i + 1]?.tipo === 'quadro' && !b.largo) {
      const dir = [];
      while (blocos[i + 1]?.tipo === 'quadro' && dir.length < 3) dir.push(blocos[++i]);
      u.push({ par: true, esq: b, dir });
    } else u.push({ par: false, b });
  }
  return u;
}

function medirPar(un) {
  const we = Math.round(CW * 0.56), gap = 16, wd = CW - we - gap;
  const e = medirPassos(un.esq, we);
  const ds = un.dir.map((q) => medirQuadro(q, wd));
  const hd = ds.reduce((s, d) => s + d.h + 10, -10);
  return {
    h: Math.max(e.h, hd), draw(x, y) {
      const c = e.draw(x, y); let yy = y;
      ds.forEach((d) => { c.push(...d.draw(x + we + gap, yy)); yy += d.h + 10; });
      return c;
    },
  };
}

// ---------------------------------------------------------------- páginas
function cabecalho(doc, p, cont) {
  const c = [
    C.rect(0, 0, A4.w, 7, { fill: COR.dourado }),
    C.rect(0, 7, 400, 5, { fill: COR.vinho }),
    C.rect(0, 12, 335, 5, { fill: COR.teal }),
    C.img('logo', 506, 29, 54, 47),
  ];
  const tg = limpar(doc.cabecalho || 'GUIA SIGAA').toUpperCase();
  linhaTexto(c, tg, M, 45, 9.5, true, COR.suave);
  if (p.faq) {
    let x = M + largura(tg, 9.5, true) + 10;
    for (const f of String(p.faq).split(/[,;]+/).map((s) => s.trim()).filter(Boolean)) {
      const t = limpar(/^faq/i.test(f) ? f.toUpperCase() : 'FAQ ' + f), tw = largura(t, 7.5, true) + 10;
      c.push(C.rect(x, 36, tw, 12, { fill: COR.vinho, r: 6 }));
      linhaTexto(c, t, x + 5, 44.8, 7.5, true, COR.branco);
      x += tw + 5;
    }
  }
  let y = 78;
  const titulo = (p.titulo || '') + (cont && p.titulo ? ' (continuação)' : '');
  if (p.secao) {
    linhaTexto(c, limpar(p.secao).toUpperCase(), M, y + 10, 10.5, true, corDaSecao(p.secao)); y += 20;
    if (titulo) { y += paragrafo(c, titulo, M, y - 1, CW, 12, true, COR.texto, 15); }
    y += 14;
  } else if (titulo) {
    y += 4 + paragrafo(c, limpar(titulo).toUpperCase(), M, y, CW, 20, true, COR.vinho, 24) + 18;
  }
  return { c, y };
}

function rodape(doc, n) {
  const c = [C.rect(0, 817, A4.w, A4.h - 817, { fill: COR.rodape })];
  const esq = limpar(doc.rodapeEsq ?? 'DIOAC | PROEN | UFMA'), meio = limpar(doc.rodapeMeio ?? '(SIGAA, 2026)');
  linhaTexto(c, esq, M + 9, 833, 9.5, false, COR.branco);
  linhaTexto(c, meio, A4.w / 2 - largura(meio, 9.5, false) / 2, 833, 9.5, false, COR.branco);
  const num = String(n), rot = limpar(doc.rodapeRot ?? 'Sumário');
  const wn = largura(num, 10, true), wr = rot ? largura(rot + ' ', 9.5, true) : 0;
  if (rot) linhaTexto(c, rot, A4.w - M - wn - wr, 833, 9.5, true, COR.branco);
  linhaTexto(c, num, A4.w - M - wn, 833, 10, true, COR.dourado);
  return c;
}

function capa(p) {
  const c = [C.rect(0, 0, A4.w, A4.h, { fill: COR.capa }), C.img('logoCapa', 157, 63, 282, 245)];
  const centro = (t, y, size, bold, cor) => { const s = limpar(t); linhaTexto(c, s, A4.w / 2 - largura(s, size, bold) / 2, y, size, bold, cor); };
  if (p.guia) centro(p.guia.toUpperCase(), 352, 10.5, true, COR.branco);
  if (p.subtitulo) {
    c.push(C.rect(155, 396, 318, 16, { fill: COR.dourado, r: 3 }));
    centro(p.subtitulo, 407.5, 10.5, true, COR.vinho);
  }
  if (p.descricao) quebrar(p.descricao, 360, 10.5).forEach((l, i) => centro(l.t, 458 + i * 14, 10.5, false, COR.branco));
  (p.rodape || '').split('\n').filter(Boolean).forEach((l, i, a) => centro(l, 800 - (a.length - 1 - i) * 12.5, 10.5, false, COR.branco));
  return c;
}

// Diagrama um documento inteiro. Devolve [{origem, cmds, avisos}] com numeração já aplicada.
// Referências {{pag:N}} (N = id da página de origem: nº do slide ou da página importada)
// viram o número que essa página recebeu no PDF final; por isso são duas passadas.
const REF = /\{\{pag:(\d+)\}\}/g;
export function diagramar(doc) {
  const temRef = (doc.paginas || []).some((p) => p.tipo === 'conteudo' && JSON.stringify(p.blocos || []).includes('{{pag:'));
  if (!temRef) return diagramarCom(doc, null);
  const mapa = new Map();
  diagramarCom(doc, new Map()).forEach((s, i) => { const id = doc.paginas[s.origem]?.id; if (id != null && !mapa.has(id)) mapa.set(id, i + 1); });
  return diagramarCom(doc, mapa);
}

function diagramarCom(doc, mapa) {
  const saida = [];
  (doc.paginas || []).forEach((p0, origem) => {
    if (p0.oculta) return;
    let p = p0, refsPerdidas = 0;
    if (mapa && p0.tipo === 'conteudo') {
      const js = JSON.stringify(p0.blocos || []);
      if (js.includes('{{pag:')) p = { ...p0, blocos: JSON.parse(js.replace(REF, (_, id) => { const n = mapa.get(+id); if (n == null) { refsPerdidas++; return mapa.size ? '?' : '00'; } return String(n); })) };
    }
    if (p.tipo === 'capa') { saida.push({ origem, cmds: capa(p), semRodape: true, avisos: [] }); return; }
    if (p.tipo === 'original') {
      const cmds = p.original ? [C.img(p.original, 0, 0, A4.w, A4.h)] : [];
      saida.push({ origem, cmds, semRodape: true, avisos: p.original ? [] : ['Página original indisponível (PPTX não é rasterizado).'] });
      return;
    }
    const centro = p.alinhamento === 'centro';
    let { c, y } = cabecalho(doc, p, false);
    let atual = { origem, cmds: c, avisos: [] };
    if (refsPerdidas && mapa.size) atual.avisos.push(`${refsPerdidas} referência(s) de página apontam para página excluída ou não incluída (aparecem como "?").`);
    saida.push(atual);
    let topoPag = y;
    const nova = () => { const h = cabecalho(doc, p, true); atual = { origem, cmds: h.c, avisos: [] }; saida.push(atual); y = topoPag = h.y; };
    for (const un of unidades(p.blocos || [])) {
      let m = un.par ? medirPar(un) : medirBloco(un.b, CW, centro);
      for (let guarda = 0; y + m.h > Y_MAX && guarda < 60; guarda++) {
        const disp = Y_MAX - y;
        const enc = m.encolher?.(disp);
        if (enc) { m = enc; break; }
        const partes = m.dividir?.(disp);
        if (partes) { atual.cmds.push(...partes[0].draw(M, y)); nova(); m = partes[1]; continue; }
        if (y === topoPag) { atual.avisos.push('Um bloco é maior que a página e foi cortado. Divida-o em partes menores.'); break; }
        nova();
      }
      atual.cmds.push(...m.draw(M, y));
      y += m.h + 16;
    }
  });
  saida.forEach((pg, i) => { if (!pg.semRodape) pg.cmds.push(...rodape(doc, i + 1)); });
  return saida;
}

// ---------------------------------------------------------------- executores
const rgb = (hex) => { const n = parseInt(hex.slice(1), 16); return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]; };
function caminhoArredondado(w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  return `M ${r} 0 L ${w - r} 0 Q ${w} 0 ${w} ${r} L ${w} ${h - r} Q ${w} ${h} ${w - r} ${h} L ${r} ${h} Q 0 ${h} 0 ${h - r} L 0 ${r} Q 0 0 ${r} 0 Z`;
}

export function desenharCanvas(ctx, cmds, imagens) {
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, A4.w, A4.h);
  for (const k of cmds) {
    if (k.k === 'rect') {
      ctx.beginPath();
      if (k.r) ctx.roundRect(k.x, k.y, k.w, k.h, Math.min(k.r, k.w / 2, k.h / 2)); else ctx.rect(k.x, k.y, k.w, k.h);
      if (k.fill) { ctx.fillStyle = k.fill; ctx.fill(); }
      if (k.stroke) { ctx.strokeStyle = k.stroke; ctx.lineWidth = k.lw || 1; ctx.stroke(); }
    } else if (k.k === 'text') {
      ctx.font = `${k.bold ? 'bold ' : ''}${k.size}px Helvetica, Arial, "Liberation Sans", sans-serif`;
      ctx.fillStyle = k.cor; ctx.fillText(k.t, k.x, k.y);
    } else if (k.k === 'circ') {
      ctx.beginPath(); ctx.arc(k.x, k.y, k.r, 0, Math.PI * 2); ctx.fillStyle = k.cor; ctx.fill();
    } else if (k.k === 'seta') {
      ctx.strokeStyle = k.cor; ctx.fillStyle = k.cor; ctx.lineWidth = k.s * 0.09;
      ctx.beginPath(); ctx.moveTo(k.x, k.y); ctx.lineTo(k.x + k.s * 0.7, k.y); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(k.x + k.s, k.y); ctx.lineTo(k.x + k.s * 0.62, k.y - k.s * 0.24); ctx.lineTo(k.x + k.s * 0.62, k.y + k.s * 0.24); ctx.closePath(); ctx.fill();
    } else if (k.k === 'img') {
      const im = imagens.get(k.src);
      if (im) ctx.drawImage(im, k.x, k.y, k.w, k.h);
    }
  }
}

export function desenharPdf(page, cmds, imagens, fontes) {
  const { rgb: RGB } = window.PDFLib;
  const cor = (h) => RGB(...rgb(h));
  const H = A4.h;
  for (const k of cmds) {
    if (k.k === 'rect') {
      const o = {};
      if (k.fill) o.color = cor(k.fill);
      if (k.stroke) { o.borderColor = cor(k.stroke); o.borderWidth = k.lw || 1; }
      if (k.r) page.drawSvgPath(caminhoArredondado(k.w, k.h, k.r), { x: k.x, y: H - k.y, ...o });
      else page.drawRectangle({ x: k.x, y: H - k.y - k.h, width: k.w, height: k.h, ...o });
    } else if (k.k === 'text') {
      if (k.t) page.drawText(k.t, { x: k.x, y: H - k.y, size: k.size, font: k.bold ? fontes.bold : fontes.reg, color: cor(k.cor) });
    } else if (k.k === 'circ') {
      page.drawCircle({ x: k.x, y: H - k.y, size: k.r, color: cor(k.cor) });
    } else if (k.k === 'seta') {
      page.drawLine({ start: { x: k.x, y: H - k.y }, end: { x: k.x + k.s * 0.7, y: H - k.y }, thickness: k.s * 0.09, color: cor(k.cor) });
      page.drawSvgPath(`M ${k.s} 0 L ${k.s * 0.62} ${-k.s * 0.24} L ${k.s * 0.62} ${k.s * 0.24} Z`, { x: k.x, y: H - k.y, color: cor(k.cor) });
    } else if (k.k === 'img') {
      const im = imagens.get(k.src);
      if (im) page.drawImage(im, { x: k.x, y: H - k.y - k.h, width: k.w, height: k.h });
    }
  }
}
