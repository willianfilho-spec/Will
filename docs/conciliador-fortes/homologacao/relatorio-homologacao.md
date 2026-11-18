# Relatório de homologação da P-004 (gerado em 2026-11-18 21:19 UTC)

**Integração com o Fortes: NÃO LIBERADA.** Liberação exige H1 a H5 aprovados, cada um com evidência.

## 1. Testes automatizados (não dependem do Fortes)

- Executados: 75 · passaram: 75 · falharam: 0
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
| Registro de “lote bloqueado” sumia da auditoria (rollback junto com a operação) | teste de fluxo completo | registro feito em transação à parte | `test_lote_fortes_completo_byte_a_byte` |
| Abas voltavam para a primeira após cada ação | teste de navegador | abas com estado preservado | `tests/e2e/fluxo_primeira_configuracao.js` |
| Teste de duplicidade mal desenhado (não exercitava o bloqueio) | mutação: a proteção foi desligada e o teste seguiu passando | teste reescrito (`test_aut_dup_02_...`); nova mutação passou a ser detectada | mutação documentada no plano de testes |

Nenhuma falha do app foi observada na instalação real, porque nenhum teste nela foi executado.
