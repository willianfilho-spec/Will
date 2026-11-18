# Conciliador Fortes

Aplicativo para conciliar extratos bancários com a contabilidade e gerar lotes de lançamentos no leiaute de
importação do Fortes Contábil. Duas interfaces sobre o mesmo núcleo e os mesmos bancos SQLite:

| Interface | Para quê | Como subir |
|---|---|---|
| **Web app** (FastAPI) | equipe **e clientes externos**: login, 2FA, portal do cliente, administração | `python scripts/rodar_web.py --demo` (demonstração) ou ver `../docs/conciliador-fortes/IMPLANTACAO.md` |
| Streamlit (legado) | uso local rápido pela equipe, sem portal do cliente nem 2FA | `streamlit run app.py` |

> **Estado honesto:** protótipo funcional, testado com dados sintéticos e com leitura de lotes reais. **A integração com
> o Fortes não está homologada** (nenhum lote gerado aqui foi importado num Fortes real) e o sistema **não passou por
> teste de intrusão independente**. Veja `../docs/conciliador-fortes/SEGURANCA.md` e
> `../docs/conciliador-fortes/homologacao/relatorio-homologacao.md`.

## Como rodar a demonstração

```bash
cd conciliador_fortes
pip install -r requirements.txt
python scripts/rodar_web.py --demo
```

Abre em `http://127.0.0.1:8000` com dados inventados. Senha de todos: `Demo-Conciliador-2026!`. Usuários:
`admin@demo.test`, `operador@demo.test`, `revisor@demo.test`, `cliente@demo.test`. O modo demo desliga o 2FA e o cookie
`Secure`; **não use em produção**.

## Pacote de teste para Windows (sem instalar nada)

Para quem vai só testar: `python scripts/montar_pacote.py` gera `Conciliador-MVP-AAAAMMDD.zip` com Python 3.12 embutido
(pacote `python` do NuGet) e todas as dependências. A pessoa extrai, dá dois cliques em `INICIAR.bat` e o navegador abre.
Dados ficam na pasta `dados` ao lado do programa. Textos para o testador: `empacotar/` (LEIA-ME, roteiro de teste, scripts
de backup e de teste do limite do histórico).
**Verificado:** o código extraído do zip sobe e roda o fluxo completo no navegador com Python 3.12 de Linux e as mesmas versões
de pacotes; a suíte passa em 3.12. **Não verificado:** a execução em Windows (o `python.exe` e as rodas compiladas para
Windows foram empacotados, mas nunca executados aqui).

## Quem faz o quê

| Papel | Pode |
|---|---|
| cliente | enviar arquivos, responder pedidos da equipe, baixar o que enviou. Nada além |
| operador | carregar, classificar, criar lançamentos manuais, conferir saldos, registrar retorno do Fortes |
| revisor | tudo do operador + segunda confirmação (movimentos e lançamentos), revisar diferença, gerar lote |
| aprovador | tudo, inclusive backup |
| admin (global) | usuários, empresas, permissões, desbloqueio, 2FA, homologação |

## Fluxo

1. **Sessão**: login, empresa ativa, papel. Toda ação grava o nome de quem fez.
2. **Cadastros**: plano de contas exportado do Fortes, Razão, regras recorrentes,
   sócios, prefixo da marca e conta do banco padrão.
3. **Cargas**: extrato OFX/CSV/XLSX e planilha de despesas. Erro de data ou valor
   recusa o arquivo inteiro; arquivo idêntico (SHA-256) é bloqueado; FITID repetido
   ou movimento parecido (mesma data, valor e histórico) gera alerta, sem exclusão automática.
4. **Revisão**: aceite em bloco das propostas de regra, classificação manual,
   natureza (transferência, tributo, sócio, incerta), itens em espera,
   decisão de duplicidade e segunda confirmação por outra pessoa.
5. **Lançamentos manuais** (web): provisões, reclassificações, transposições e ajustes que não vêm do extrato
   (ex.: D despesa / C INSS a recolher). Criação por uma pessoa, confirmação obrigatória por outra, entrada no mesmo
   lote. Aceita importar arquivo no leiaute do Fortes.
6. **Conferência e exportação**: saldo inicial + movimentação = saldo final do extrato; extrato × contabilidade;
   **extrato × Razão movimento a movimento** (diferenças classificadas); justificativa e segunda revisão;
   geração do lote; registro de aceite ou rejeição no Fortes; conferência do lote no Razão depois da importação.
7. **Portal do cliente** (web): envio de arquivos (cifrados em disco), pedidos da equipe e respostas.

## Travas que não dá para contornar pela tela

- Segunda confirmação obrigatória para valor ≥ limite da empresa (R$ 10.000,00 por
  padrão), sócio, natureza incerta e duplicidade mantida. Quem revisou não confirma.
- O lote não sai se houver: conta inexistente ou sintética, partida sem conta,
  débito igual a crédito, valor ≤ 0, item de risco sem segunda confirmação,
  duplicidade sem decisão, movimento do período sem revisão (classifique ou ponha
  em espera), conferência de saldo não feita, ou diferença sem justificativa
  revisada por outra pessoa. Conciliação com diferença fica `justificada`, nunca `concluida`.
- Valor só em centavos (INTEGER); fração de centavo é recusada.
- Cada empresa tem banco e pasta próprios; abrir uma empresa sem permissão é negado
  e registrado em `audit_acesso`.

## Leiaute do Fortes

Conferido em arquivos reais aceitos pelo Fortes no escritório:
`data;debito;credito;valor;historico;;;;`, sem cabeçalho, ASCII, CRLF, contas pelo
**código reduzido**, valor positivo com vírgula e sem milhar, histórico terminado
pela marca `[PREFIXO-AAAAMM-NNNNNN]`. Importe com "Desconsiderar Identificador" e
"Utilizar Código Reduzido" marcados.

## Homologação (P-004)

A integração com o Fortes **não está homologada**. Cinco itens dependem da instalação real (H1 importação de
lote, H2 limite do histórico, H3 formato do Razão, H4 restauração de backup na base do escritório, H5 extratos
reais) e só viram "aprovado" com evidência anexada. O app mostra o aviso até todos serem aprovados.

- Plano, matriz, instruções e relatório: `../docs/conciliador-fortes/homologacao/`
- Atualizar matriz e relatório: `python scripts/relatorio_homologacao.py`
- Teste de restauração isolada: `python scripts/teste_restauracao.py`
- Arquivo de teste do limite do histórico: `python scripts/gerar_lote_homologacao.py --help`

Já automatizado: limite do histórico configurável por empresa (40 a 250; padrão 118, não validado) com o
histórico completo preservado; travas no banco contra alteração de origem, exportados, lotes e auditoria;
bloqueio de duplicidade contra o Razão e contra lotes anteriores; releitura do arquivo gerado antes de liberar;
conferência do lote no Razão depois da importação; verificação de SHA-256 dos originais e dos lotes.

## Testes

```bash
python -m pytest          # inclui segurança web, fluxo completo por HTTP, lançamentos manuais, conciliação, homologação
```

Testes de navegador: ver `tests/e2e/LEIAME.md`.

## Estrutura

```
app.py                 entrada e navegação
config.py              caminhos, ENABLE_AI=False, limites
domain/                money, rules_engine, deduplicator, risk_evaluator, reconciler, operacoes (casos de uso)
parsers/               ofx, tabular (CSV/XLSX), plano e razão do Fortes
exporters/             validador pré-exportação e gerador do leiaute
ai/suggester.py        interface desligada; se ligada, só sugere
storage/               database (central.db e contabil.db), usuarios, audit, backup
web/                   web app (FastAPI): rotas, templates, segurança
ui/                    telas do Streamlit (legado)
scripts/               seed_demo, restaurar_backup, teste_restauracao, gerar_lote_homologacao, relatorio_homologacao
exemplos/              arquivos sintéticos
```

Para clientes externos: o app tem o portal e os controles de segurança descritos em `SEGURANCA.md`, mas exige HTTPS
via proxy, chave de criptografia configurada e disco cifrado. Faltam recuperação de senha por e-mail e teste de intrusão.
