# Projeto contábil: conciliação bancária e lançamentos para o Fortes

@AGENTS.md

As regras do `AGENTS.md` valem para qualquer agente, inclusive o Claude Code,
e prevalecem sobre este arquivo em caso de conflito. Este arquivo acrescenta
como o trabalho é orquestrado.

## Contexto do projeto

- Objetivo: o piloto testa o aplicativo em uso real para depois oferecê-lo
  como produto. Toda função de análise (motor e conferência do banco) deve
  produzir resultado verificável e relatório PDF para revisão e auditoria
  humana (`motor_contabil/relatorios.py`).
- Aplicação Python com interface Streamlit, rodando no computador do
  escritório (fase 1). Dados de cada empresa cliente ficam em `dados/<empresa>/`,
  fora do Git.
- Destino contábil: arquivo de importação do Fortes
  (`motor_contabil/exportador_fortes.py`). O leiaute foi tirado de arquivos
  reais aceitos pelo Fortes e é protegido pelo teste
  `test_leiaute_fortes_byte_a_byte`. Nenhuma demanda altera esse leiaute sem
  um novo arquivo real aceito pelo Fortes que justifique a mudança.
- Comandos: `pytest` (na pasta `automacao-contabil`), `python -m pyflakes
  app.py motor_contabil testes` e, para a interface,
  `streamlit.testing.v1.AppTest` (ver `testes/`).
- O repositório é público. Nenhum extrato, plano de contas, regra com nome de
  favorecido ou arquivo `.db` de cliente entra em commit, nem em exemplo, nem
  em teste. Testes usam só dados fictícios.

## Orquestração das demandas

A sessão principal coordena: entende a demanda, planeja, delega o trabalho
independente, integra e verifica. Ao começar, informe o modelo em uso quando
puder confirmá-lo.

Cada demanda chega com **modo** (EXECUTAR ou IMPLANTAR), **demanda**,
**critérios de aceitação** e **restrições**. Sem critérios, derive-os da
demanda e registre as suposições. No modo EXECUTAR sem demanda, peça a
descrição antes de começar.

### 1. Inspecionar e planejar

Leia `AGENTS.md` e `README.md`, examine `git status` e identifique os
comandos de teste. Mapeie o comportamento atual e os arquivos afetados. Monte
uma tabela com ID, frente, entrega, dependências, arquivos sob
responsabilidade, modelo e critério de conclusão, ativando só as subtarefas
necessárias:

| ID | Frente | Entrega de referência |
|---|---|---|
| T1 | Tela | Mapear o fluxo do usuário e os componentes afetados |
| T2 | Tela | Implementar o comportamento na interface |
| T3 | Tela | Verificar os estados relevantes e a acessibilidade |
| Q1 | Testes | Traduzir os critérios de aceitação em cenários verificáveis |
| Q2 | Testes | Criar ou ajustar testes para as regressões pertinentes |
| Q3 | Testes | Executar as verificações e registrar o resultado |
| D1 | Documentação | Identificar os trechos afetados pela mudança |
| D2 | Documentação | Atualizar instruções e exemplos de uso |
| D3 | Documentação | Conferir exemplos e instruções com o código integrado |

### 2. Delegar por dependência

Use a ferramenta `Agent` com os perfis de `.claude/agents/`: `tela`
(T1–T3), `testes` (Q1–Q3) e `documentacao` (D1–D3). Eles rodam em Sonnet; a
sessão principal mantém o plano, as decisões compartilhadas e a integração.

- Envie a cada agente só o necessário: ID, objetivo, arquivos autorizados,
  dependências, resultado esperado e como validar.
- Em paralelo, só o que é independente: mapeamento da tela, desenho dos
  cenários de teste e inventário da documentação. Testes de integração e
  revisão final dos exemplos esperam a implementação.
- Um único responsável por arquivo em cada rodada. Com risco de edição
  concorrente, use worktrees com a base certa ou execute em sequência.
- Sem a ferramenta `Agent`, execute as frentes em sequência e informe que a
  delegação não estava disponível.

### 3. Integrar e verificar

Revise os diffs, integre na ordem das dependências e preserve o trabalho
local do usuário. No estado integrado, rode `pytest`, `pyflakes` e a
verificação da interface. Falhou: investigue, corrija o que estiver no escopo
e rode de novo. Cada critério de aceitação precisa de evidência observável.

### 4. Entregar

Informe o que mudou, os agentes e modelos usados (quando confirmados), as
verificações e seus resultados, as pendências e os critérios ainda sem
evidência. Use o progresso "tarefas verificadas de tarefas ativadas", por
exemplo `6 de 7`.

### Modo IMPLANTAR

Configura este fluxo (este arquivo e os perfis) sem executar demanda de
produto, a não ser que ela seja pedida.
