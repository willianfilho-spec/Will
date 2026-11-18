# Decisões

Atualizado em: 2026-11-18
Formato: ID, data, decisão, justificativa, alternativas, consequências, status (vigente | substituída por D-XXX). Nunca apagar; substituir.

## D-001 [2026-11-17] Memória vive no repositório git
- Decisão: arquivos Markdown em `memoria/`, `CLAUDE.md` na raiz e hooks em `.claude/settings.json`, tudo versionado.
- Justificativa: as sessões rodam em containers efêmeros; `~/.claude` (memória global e hooks do usuário) é descartado ao fim. O clone do repositório é a única coisa que reaparece em toda sessão.
- Alternativas: `~/.claude/CLAUDE.md` (perdido a cada sessão); conectores externos como Notion (dependem de autenticação e de rede; não testados aqui).
- Consequências: a memória só persiste depois de commit + push; o git dá histórico e reversão de graça.
- Status: vigente. Origem: diagnóstico do ambiente; confiança: alta.

## D-002 [2026-11-17] Política de repositório público
- Decisão: só registrar o que poderia ser publicado; verificador bloqueia e-mail, CPF, telefone, tokens e senhas.
- Justificativa: `willianfilho-spec/Will` é público.
- Alternativas: migrar a memória para um repositório privado (avaliada e descartada em D-004).
- Consequências: `pessoas.md` não foi criado; contexto pessoal fica limitado.
- Status: vigente. Origem: verificação da visibilidade do repositório; confiança: alta.

## D-003 [2026-11-17] Automação mínima: dois hooks
- Decisão: `SessionStart` mostra o estado da memória e guarda o commit inicial; `Stop` pede revisão uma única vez por sessão, só se houve mudança no projeto sem mudança na memória. A consolidação em si é feita pelo Claude seguindo a skill `salvar-memoria`.
- Justificativa: um hook de comando não lê a conversa de forma confiável nem resume conteúdo; quem pode decidir o que é durável é o modelo. `SessionEnd` não pode pedir nada ao Claude e, na nuvem, o container pode ser recolhido sem evento.
- Alternativas: gravar transcrições inteiras (crescimento ilimitado, risco de vazar dados num repositório público); lembrete a cada resposta (ruído).
- Status: vigente. Origem: análise da documentação de hooks e do ambiente; confiança: alta.

## D-004 [2026-11-17] Memória permanece neste repositório público (encerra P-001)
- Decisão: manter `memoria/` em `willianfilho-spec/Will`, sob a política de D-002. Decidida pelo Claude a pedido do usuário ("decida").
- Justificativa: (1) o workflow `pages.yml` publica `guia-sigaa-editor/` e `editor-pdf/` a partir da `main`; tornar o repositório privado exigiria plano pago para manter o GitHub Pages; (2) memória em outro repositório não é carregada automaticamente nas sessões deste, porque `CLAUDE.md` só importa arquivos do clone; cada sessão teria de anexar o outro repositório; (3) a automação já testada funciona aqui.
- Alternativas: repositório privado só para memória; tornar este repositório privado.
- Consequências: a memória continua restrita a informação publicável. Reabrir esta decisão se surgir necessidade real de guardar contexto sensível.
- Status: vigente. Origem: análise do repositório; confiança: alta.

## D-005 [2026-11-17] Exceção à declaração de autoria humana (encerra P-003)
- Decisão: registrar em `Human-Written Declaration` que `CLAUDE.md`, `memoria/` e `.claude/` são mantidos com auxílio de IA e ficam fora do compromisso de autoria humana.
- Justificativa: manter a declaração verdadeira. Aprovado pelo usuário.
- Status: vigente. Origem: pedido do usuário; confiança: alta.

## D-006 [2026-11-18] Fluxo de orquestração implantado por repositório
- Decisão: o fluxo "Opus coordena, subagentes executam" fica no `CLAUDE.md` de cada repositório, com três perfis em `.claude/agents/` (`tela`, `testes`, `documentacao`, `model: sonnet`). Implantado em `Will`, no repositório do dataset da APA Maracanã e no repositório privado do laudo de viabilidade. As frentes foram adaptadas: no laudo, "tela" é a apresentação do PDF; no dataset, a apresentação do Markdown no GitHub.
- Isolamento: nenhum perfil fixa `isolation: worktree` no cabeçalho. O coordenador escolhe `isolation: "worktree"` por chamada, porque o worktree nasce do último commit e não leva alterações não commitadas.
- Justificativa: cada sessão clona só os repositórios dela, e `~/.claude` é descartado (D-001); configuração por repositório é a única que persiste. Escolher o worktree por chamada evita subagente trabalhar numa base sem as mudanças locais.
- Alternativas: skill compartilhada entre repositórios (não carrega fora do repositório onde está); worktree fixo nos perfis (risco de base desatualizada).
- Consequências: atualizar o fluxo exige editar os três repositórios. Haiku entra só por `model: "haiku"` na chamada do `Agent`.
- Status: vigente quanto aos perfis e ao isolamento por worktree; a regra "delegar sempre que houver mais de uma frente" foi substituída por D-007. Origem: pedido do usuário (modo IMPLANTAR); confiança: alta.

## D-007 [2026-11-18] Política de execução e delegação: subagente não é padrão
- Decisão: a seção "Orquestração" dos três `CLAUDE.md` virou "Política de execução e delegação". Antes de executar, o coordenador escolhe entre execução direta, sequencial ou paralela, e registra o motivo. Paralelo só com tarefas independentes, áreas de escrita isoladas e ganho maior que o custo de contexto. Regras por repositório: Will pode delegar componentes independentes; laudo trabalha em sequência, sem concorrência em `gerar_laudo.py`; dataset não gera código sem requisitos e corrige só divergências verificadas entre README e repositório.
- Justificativa: política definida pelo usuário; reduz custo de contexto e risco de conflito.
- Alternativas: manter a delegação por frente como padrão (D-006 original).
- Consequências: os perfis continuam disponíveis, mas só são usados quando a estratégia justificar. Em sessão com vários repositórios, os perfis de mesmo nome colidem; a política manda conferir a descrição antes de usar.
- Status: vigente. Origem: política de execução enviada pelo usuário em 2026-11-18; confiança: alta.
