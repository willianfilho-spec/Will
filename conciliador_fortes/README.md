# Conciliador Fortes (MVP · Etapa A)

Aplicativo local para conciliar extratos bancários com a contabilidade e gerar
lotes de lançamentos no leiaute de importação do Fortes Contábil. Feito para
uso interno do escritório (Etapa A): roda numa máquina, abre no navegador e
guarda tudo em SQLite.

## Como rodar

```bash
cd conciliador_fortes
pip install -r requirements.txt
streamlit run app.py
```

Na primeira vez, a tela pede o administrador e a primeira empresa. Os dados
ficam em `conciliador_fortes/data/` (ou na pasta de `CONCILIADOR_DATA_DIR`),
que **nunca** deve ir para o git.

Para conhecer o fluxo com dados inventados:

```bash
CONCILIADOR_DATA_DIR=/tmp/demo python scripts/seed_demo.py
CONCILIADOR_DATA_DIR=/tmp/demo streamlit run app.py
```

Logins da demonstração (senha `demo-1234`): `operador@demo.test`,
`revisor@demo.test`, `admin@demo.test`.

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
5. **Conferência e exportação**: saldo inicial + movimentação = saldo final do
   extrato; extrato x contabilidade; justificativa e segunda revisão de diferença;
   geração do lote; registro de aceite ou rejeição no Fortes.

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

## O que ainda não está confirmado

| Item | Situação | Como fechar |
|---|---|---|
| Aceitação de um lote gerado por este app | Não testado no Fortes | Importar um lote de teste numa empresa de homologação |
| Limite do histórico (118 caracteres) | Herdado do exportador anterior; há arquivo real com 123 | Testar um histórico longo no Fortes |
| Leiaute do Razão exportado pelo Fortes | Sem arquivo real; o leitor tabular é genérico | Enviar um Razão real (anonimizado) |
| Extratos reais dos bancos do piloto | Testado só com OFX e CSV sintéticos | Rodar com 1 OFX e 1 CSV/XLSX reais |
| Restauração de backup na máquina do escritório | Testada só em teste automatizado | Fazer uma restauração prática (critério de aceite) |

## Testes

```bash
python -m pytest          # 47 testes: dinheiro, leitores, fluxo completo, validadores, isolamento, backup
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
ui/                    telas
scripts/               seed_demo.py, restaurar_backup.py
exemplos/              arquivos sintéticos
```

Etapa B (clientes enviando pelo navegador) não está pronta: o servidor escuta
só em `localhost` e não há HTTPS, recuperação de senha nem testes de intrusão.
