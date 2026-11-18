// Fluxo completo do web app em navegador real. Requer: python scripts/rodar_web.py --demo --port 8611
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), os = require('os');
const URL = process.env.E2E_URL || 'http://localhost:8611', OUT = process.env.E2E_OUT || os.tmpdir();
const EX = path.join(__dirname, '..', '..', 'exemplos');
const SENHA = 'Demo-Conciliador-2026!';
(async () => {
  const browser = await chromium.launch();
  const problemas = [];
  async function pessoa(email) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
    const page = await ctx.newPage();
    page.on('console', m => { if (['error', 'warning'].includes(m.type()) && !(m.text().includes('403') && email.startsWith('cliente'))) problemas.push(`[${email}] console ${m.type()}: ${m.text()}`); });  // o 403 do cliente na área da equipe é proposital
    page.on('pageerror', e => problemas.push(`[${email}] pageerror: ${e}`));
    page.on('requestfailed', r => { if (!r.url().endsWith('/baixar')) problemas.push(`[${email}] falha de rede: ${r.url()}`); });  // download de anexo aparece como navegação abortada
    await page.goto(URL + '/login');
    await page.getByLabel('E-mail').fill(email); await page.getByLabel('Senha').fill(SENHA);
    await page.getByRole('button', { name: 'Entrar' }).click();
    await page.waitForURL('**/painel');
    return { ctx, page };
  }
  const msg = async p => (await p.locator('.msg').allInnerTexts()).filter(t => !t.includes('não homologada')).join(' | ');
  const shot = (p, n) => p.screenshot({ path: `${OUT}/web_${n}.png`, fullPage: true });

  // ---------- operadora
  let { ctx, page } = await pessoa('operador@demo.test');
  await shot(page, '01_painel');
  await page.goto(URL + '/e/demo'); await shot(page, '02_resumo');
  await page.goto(URL + '/e/demo/revisao'); await shot(page, '03_revisao');
  await page.locator('input[name=ids]').evaluateAll(els => els.forEach(e => e.checked = true));
  await page.getByRole('button', { name: 'Aceitar marcadas' }).click();
  console.log('1. aceitar:', await msg(page));
  await page.goto(URL + '/e/demo/revisao/mov/4');
  await page.locator('select[name=conta]').selectOption('56');
  await page.locator('input[name=historico]').fill('PAGTO FORNECEDOR PAPELARIA GAMA');
  await page.getByRole('button', { name: 'Classificar', exact: true }).click();
  console.log('2. sispag:', await msg(page));
  await page.goto(URL + '/e/demo/revisao/mov/5');
  await page.locator('select[name=conta]').selectOption('90'); await page.locator('select[name=natureza]').selectOption('socio');
  await page.getByRole('button', { name: 'Classificar', exact: true }).click();
  console.log('3. sócio:', await msg(page));
  await page.goto(URL + '/e/demo/lancamentos');
  await page.locator('select[name=tipo]').first().selectOption('provisao');
  await page.locator('input[name=data]').fill('2026-09-30');
  await page.locator('select[name=debito]').selectOption('259'); await page.locator('select[name=credito]').selectOption('57');
  await page.locator('input[name=valor]').fill('1.234,56'); await page.locator('input[name=historico]').fill('PROVISAO INSS 09/2026');
  await page.getByRole('button', { name: 'Criar lançamento' }).click();
  console.log('4. lançamento:', await msg(page)); await shot(page, '04_lancamentos');
  await page.goto(URL + '/e/demo/conferencia?periodo=2026-09&conta=362');
  await page.getByRole('button', { name: 'Gravar e conferir' }).click();
  console.log('4b. conferência:', await msg(page));
  await page.goto(URL + '/e/demo/conferencia?periodo=2026-09&conta=362'); await shot(page, '05_conferencia');
  await page.goto(URL + '/e/demo/exportacao?periodo=2026-09&conta=362'); await shot(page, '06_exportacao_bloqueada');
  console.log('5. exportação (operadora):', (await page.locator('.msg.erro').allInnerTexts()).join(' | ').slice(0, 300));
  await ctx.close();

  // ---------- revisor
  ({ ctx, page } = await pessoa('revisor@demo.test'));
  await page.goto(URL + '/e/demo/revisao?aba=segunda');
  await page.getByRole('button', { name: 'Confirmar', exact: true }).click();
  console.log('6. segunda confirmação:', await msg(page));
  await page.goto(URL + '/e/demo/lancamentos');
  await page.getByRole('button', { name: 'Confirmar', exact: true }).click();
  console.log('7. lançamento confirmado:', await msg(page));
  await page.goto(URL + '/e/demo/exportacao?periodo=2026-09&conta=362'); await shot(page, '07_exportacao_pronta');
  await page.getByRole('button', { name: 'Gerar lote' }).click();
  console.log('8. lote:', await msg(page)); await shot(page, '08_lote');
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Baixar arquivo' }).first().click()]);
  const f = `${OUT}/lote_web.csv`; await dl.saveAs(f);
  const linhas = fs.readFileSync(f, 'latin1').split('\r\n');
  console.log('9. arquivo baixado:', linhas.length - 1, 'linhas; CRLF ok:', linhas.at(-1) === '', '| 9 campos:', linhas.slice(0, -1).every(l => l.split(';').length === 9));
  console.log('   ', linhas.at(-2));
  await ctx.close();

  // ---------- cliente
  ({ ctx, page } = await pessoa('cliente@demo.test'));
  await shot(page, '09_painel_cliente');
  await page.goto(URL + '/c/demo');
  await page.locator('input[type=file]').setInputFiles(path.join(EX, 'despesas_exemplo.csv'));
  await page.locator('select[name=categoria]').selectOption('planilha');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  console.log('10. cliente enviou:', await msg(page)); await shot(page, '10_portal');
  const r = await page.goto(URL + '/e/demo'); console.log('11. cliente na área da equipe ->', r.status());
  await ctx.close();

  // ---------- administrador
  ({ ctx, page } = await pessoa('admin@demo.test'));
  await page.goto(URL + '/admin'); await shot(page, '11_admin');
  await ctx.close();
  await browser.close();
  console.log('\nproblemas de console/rede:', problemas.length ? problemas : 'nenhum');
  process.exit(problemas.length ? 1 : 0);
})().catch(e => { console.error('FALHA', e.message); process.exit(1); });
