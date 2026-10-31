// Guarda o último PDF aberto e suas anotações no IndexedDB deste navegador.
const BANCO = 'folha-clara', LOJA = 'sessao', CHAVE = 'atual';

function abrir() {
  return new Promise((ok, erro) => {
    const req = indexedDB.open(BANCO, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(LOJA);
    req.onsuccess = () => ok(req.result);
    req.onerror = () => erro(req.error);
  });
}

async function operar(modo, fn) {
  const db = await abrir();
  try {
    return await new Promise((ok, erro) => {
      const tx = db.transaction(LOJA, modo);
      const req = fn(tx.objectStore(LOJA));
      tx.oncomplete = () => ok(req?.result);
      tx.onerror = () => erro(tx.error);
      tx.onabort = () => erro(tx.error);
    });
  } finally { db.close(); }
}

export const salvarSessao = s => operar('readwrite', loja => loja.put({ ...s, salvoEm: Date.now() }, CHAVE));
export const lerSessao = () => operar('readonly', loja => loja.get(CHAVE));
export const apagarSessao = () => operar('readwrite', loja => loja.delete(CHAVE)).catch(() => {});
