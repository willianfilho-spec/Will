const { chromium } = require('playwright');
const OUT = process.env.E2E_OUT || require('os').tmpdir(), URL = process.env.E2E_URL || 'http://localhost:8599';
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, acceptDownloads: true });
  const erros = []; page.on('pageerror', e => erros.push(String(e)));
  const esperar = async () => { await page.waitForTimeout(700); await page.waitForSelector('[data-testid="stStatusWidget"]', { state: 'detached', timeout: 20000 }).catch(() => {}); await page.waitForTimeout(400); };
  const exc = async (onde) => { if (await page.locator('[data-testid="stException"]').count()) throw new Error(onde + ': ' + await page.locator('[data-testid="stException"]').first().innerText()); };
  const alerta = async () => (await page.locator('[data-testid="stAlert"]').allInnerTexts()).join(' | ');
  async function entrar(email) { await page.goto(URL); await esperar(); await page.getByLabel('E-mail').fill(email); await page.getByLabel('Senha').fill('demo-1234'); await page.getByRole('button', { name: 'Entrar' }).click(); await esperar(); await exc('login'); }
  async function sair() { await page.getByRole('button', { name: 'Sair' }).click(); await esperar(); }
  async function ir(nome) { await page.getByRole('link', { name: nome }).click(); await esperar(); await exc(nome); }
  async function escolher(rotulo, texto) { await page.getByLabel(rotulo, { exact: true }).first().click(); await page.waitForTimeout(300); await page.keyboard.type(texto); await page.waitForTimeout(300); await page.keyboard.press('Enter'); await esperar(); }

  await entrar('operador@demo.test');
  await ir('Revisão');
  await page.getByText('Marcar todas').click(); await esperar();
  await page.getByRole('button', { name: 'Aceitar propostas marcadas' }).click(); await esperar(); await exc('aceitar');
  console.log('1.', await alerta());
  // movimento 4 (SISPAG) agora é o primeiro da fila
  await escolher('Contrapartida', '56 ');
  await page.getByLabel('Histórico contábil').fill('PAGTO FORNECEDOR PAPELARIA GAMA');
  await page.getByRole('button', { name: 'Classificar', exact: true }).click(); await esperar(); await exc('classificar sispag');
  console.log('2.', await alerta());
  await escolher('Contrapartida', '90 ');
  await escolher('Natureza', 'socio');
  await page.getByRole('button', { name: 'Classificar', exact: true }).click(); await esperar(); await exc('classificar socio');
  console.log('3.', await alerta());
  await page.locator('[data-testid=\"stButtonGroup\"]').getByText(/Segunda confirmação/).first().click(); await esperar();
  console.log('4. operadora vê:', (await page.locator('[data-testid="stAlert"], [data-testid="stNotification"]').allInnerTexts()).join(' | '));
  await page.screenshot({ path: `${OUT}/10_segunda_operadora.png` });
  await ir('Conferência e exportação');
  await page.screenshot({ path: `${OUT}/11_conferencia.png`, fullPage: true });
  await page.getByRole('button', { name: 'Refazer conferência' }).click(); await esperar(); await exc('conferir');
  console.log('5.', await alerta());
  await sair();

  await entrar('revisor@demo.test');
  await ir('Revisão');
  await page.locator('[data-testid=\"stButtonGroup\"]').getByText(/Segunda confirmação/).first().click(); await esperar();
  await page.getByRole('button', { name: 'Confirmar' }).click(); await esperar(); await exc('confirmar');
  console.log('6.', await alerta());
  await ir('Conferência e exportação');
  console.log('7.', await alerta());
  await page.getByRole('button', { name: 'Gerar lote' }).click(); await esperar(); await exc('gerar');
  console.log('8.', await alerta());
  await page.screenshot({ path: `${OUT}/12_lote.png`, fullPage: true });
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Baixar arquivo' }).first().click()]);
  await dl.saveAs(`${OUT}/lote_baixado.csv`);
  await page.getByRole('button', { name: 'Importado sem erro' }).click(); await esperar(); await exc('retorno');
  console.log('9.', await alerta());
  // simula o Razão exportado depois da importação: abertura + o próprio lote
  const fs = require('fs');
  const razao = `${OUT}/razao_pos_importacao.csv`;
  fs.writeFileSync(razao, Buffer.concat([Buffer.from('31/08/2026;362;90;10000,00;SALDO DE ABERTURA;;;;\r\n'), fs.readFileSync(`${OUT}/lote_baixado.csv`)]));
  await page.waitForTimeout(1500);
  await ir('Cadastros');
  await page.locator('[data-testid="stButtonGroup"]').getByText('Razão', { exact: true }).click(); await esperar();
  await page.locator('[data-testid="stFileUploader"]').filter({ hasText: 'Arquivo do Razão' }).locator('input[type=file]').setInputFiles(razao); await esperar();
  await page.getByRole('button', { name: 'Carregar Razão' }).click(); await esperar(); await exc('razao');
  console.log('10.', await alerta());
  await ir('Conferência e exportação');
  await page.getByRole('button', { name: 'Conferir lote no Razão' }).click(); await esperar(); await exc('conferir razao');
  console.log('11.', await alerta());
  await page.screenshot({ path: `${OUT}/13_conferencia_razao.png`, fullPage: true });
  await sair();
  await entrar('admin@demo.test');
  console.log('12. barra lateral:', (await page.locator('[data-testid="stSidebar"] [data-testid="stAlert"]').allInnerTexts()).join(' | '));
  await page.getByText('Registrar resultado de teste').click(); await esperar();
  await page.getByLabel('Status').click(); await page.keyboard.type('aprovado'); await page.keyboard.press('Enter'); await esperar();
  await page.getByLabel('Teste realizado (o que foi feito, em qual empresa/arquivo)').fill('teste e2e sem evidencia anexada');
  await page.getByLabel('Resultado observado').fill('nao deve ser aceito pelo sistema');
  await page.getByLabel('Referência').fill('demo:1');
  await page.getByRole('button', { name: 'Registrar' }).click(); await esperar(); await exc('hom');
  console.log('13.', (await page.locator('[data-testid="stAlert"]').allInnerTexts()).filter(t => /evid|Bloq|exige/.test(t)).join(' | '));
  await page.screenshot({ path: `${OUT}/14_homologacao.png`, fullPage: true });
  await browser.close();
  console.log('erros JS:', erros);
})().catch(e => { console.error('FALHA', e.message); process.exit(1); });
