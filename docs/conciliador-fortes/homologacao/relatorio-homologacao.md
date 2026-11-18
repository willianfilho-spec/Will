# Relatório de homologação da P-004 (gerado em 2026-11-18 22:03 UTC)

**Integração com o Fortes: NÃO LIBERADA.** Liberação exige H1 a H5 aprovados, cada um com evidência.

## 1. Testes automatizados (não dependem do Fortes)

- Executados: 122 · passaram: 122 · falharam: 0
- Testes citados na matriz que não existem: 0
- Escopo: leitura de arquivos, regras, validadores, travas do banco, duplicidade, integridade, backup/restauração em pasta temporária. Usam só dados sintéticos.
- O que eles **não** provam: que o Fortes aceita o arquivo, o limite do histórico, o formato do Razão real, o comportamento com extratos reais.

## 2. Testes que dependem da instalação real do Fortes

Estado lido dos registros de homologação (`central.db`). Item sem registro com evidência fica **não testado**.

### H1 · Importação real de lote no Fortes

- **Estado: NÃO TESTADO NA INSTALAÇÃO REAL.**
- Critério de aprovação: Um lote gerado pelo app é importado no Fortes sem erro e todas as marcas aparecem no Razão exportado depois, uma vez só, com data, valor e contas iguais.
- Evidência: nenhuma registrada.
- Procedimento: `instrucoes-escritorio.md`, seção H1.

### H2 · Limite de caracteres do histórico

- **Estado: NÃO TESTADO NA INSTALAÇÃO REAL.**
- Critério de aprovação: O Fortes aceita o histórico no tamanho configurado sem cortar a marca [PREFIXO-AAAAMM-NNNNNN].
- Evidência: nenhuma registrada.
- Procedimento: `instrucoes-escritorio.md`, seção H2.

### H3 · Leiaute do Razão exportado pelo Fortes

- **Estado: NÃO TESTADO NA INSTALAÇÃO REAL.**
- Critério de aprovação: Um Razão real, exportado do Fortes, é lido pelo app e o saldo do banco bate com o mostrado no Fortes.
- Evidência: nenhuma registrada.
- Procedimento: `instrucoes-escritorio.md`, seção H3.

### H4 · Backup e restauração

- **Estado: NÃO TESTADO NA INSTALAÇÃO REAL.**
- Critério de aprovação: Backup restaurado em pasta isolada na máquina do escritório, com contagens, SHA-256 e integridade iguais aos da origem.
- Evidência: nenhuma registrada.
- Procedimento: `instrucoes-escritorio.md`, seção H4.

### H5 · Extratos reais do piloto

- **Estado: NÃO TESTADO NA INSTALAÇÃO REAL.**
- Critério de aprovação: Um OFX e um CSV/XLSX reais de cada banco do piloto são carregados sem erro estrutural e o saldo final calculado bate com o do extrato.
- Evidência: nenhuma registrada.
- Procedimento: `instrucoes-escritorio.md`, seção H5.

## 3. Falhas identificadas e ações corretivas (histórico da construção)

| Falha | Como apareceu | Ação corretiva | Evidência |
|---|---|---|---|
| Formulários do web app renderizavam `<Macro 'csrf'>` no lugar do token (nome da macro igual ao da variável); toda ação autenticada caía em 403 | teste HTTP `test_web_05` | macro renomeada para `csrf_campo` | `test_web_*` passando |
| Conexão SQLite criada numa thread e usada em outra (FastAPI) derrubava o login | teste HTTP `test_web_01` | `check_same_thread=False` (conexão por requisição, uso sequencial) | `test_web_*` |
| Mutação da cadeia de auditoria (desligar a checagem de encadeamento) sobreviveu | verificação por mutação | `test_aud_03` (hash próprio válido com elo forjado; linha sem hash inserida por fora) | mutação agora detectada |
| Segregação de função comparava o nome do usuário (homônimos se confundiriam) | revisão de projeto ao abrir o sistema a vários usuários | identidade passa a incluir o id (`Nome #id`) | `test_doc_02`, `test_segregacao_de_funcao` |
| Meu próprio validador tratava marca repetida como erro, mas na prática do escritório a reclassificação reaproveita a marca do movimento original | pré-validação dos lotes reais (4 casos em `COMPLETO_v13`) | marca repetida em lançamentos diferentes virou aviso; linha idêntica segue como erro | `test_scr_01` |
| Registro de “lote bloqueado” sumia da auditoria (rollback junto com a operação) | teste de fluxo completo | registro feito em transação à parte | `test_lote_fortes_completo_byte_a_byte` |
| Abas voltavam para a primeira após cada ação | teste de navegador | abas com estado preservado | `tests/e2e/fluxo_primeira_configuracao.js` |
| Teste de duplicidade mal desenhado (não exercitava o bloqueio) | mutação: a proteção foi desligada e o teste seguiu passando | teste reescrito (`test_aut_dup_02_...`); nova mutação passou a ser detectada | mutação documentada no plano de testes |

Nenhuma falha do app foi observada na instalação real, porque nenhum teste nela foi executado.

## 4. Verificação com arquivos reais do escritório (pré-validação; NÃO é o item H1)

Executada em 2026-11-18, em sessão de trabalho, com os arquivos enviados pelo escritório (não versionados). Reproduzível com `scripts/validar_lote_existente.py`. O que prova: o leiaute e o leitor do app lidos sobre lotes reais e a consistência contábil dos lotes. O que não prova: que o Fortes aceita um lote gerado pelo app.

| Verificação | Resultado |
|---|---|
| 32 arquivos de lançamentos (`importacao_FORTES_NX_*.csv`) lidos pelo leitor do app | 32 lidos, 0 erros |
| `COMPLETO_v13`: 2.083 lançamentos, 9 campos, ASCII, CRLF, sem linha idêntica repetida | sem problemas |
| Saldo da conta 362 em 31/12/2025 e em 27/10/2026 (esperados +43.028,71 e −388,80, do prompt do agente) | bate em `COMPLETO_v10` a `v13`, `FINAL`, `CONSOLIDADO_COMPLETO` e `BASE_CORRIGIDA_SOCIOS`; **não** bate em `UNIFICADO_v9_FINAL` (iteração anterior) |
| Marcas repetidas em lançamentos diferentes | 4 casos (reclassificações `D 2 / C 375` reaproveitando a marca do recebimento); tratado como aviso |
| `AJUSTE_INSS_MULTA_JUROS_DARF` (12 lançamentos) | estrutura válida; contas não conferidas por falta do plano de contas |
| Contas contra o plano de contas real | **não feito** (o plano não foi enviado) |
| Extrato bruto (OFX/CSV/PDF) | **não feito** (não enviado) |
