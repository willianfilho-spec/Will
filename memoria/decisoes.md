# Decisões

Atualizado em: 2026-11-17
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
- Alternativas: migrar a memória para um repositório privado (ver P-001).
- Consequências: `pessoas.md` não foi criado; contexto pessoal fica limitado.
- Status: vigente. Origem: verificação da visibilidade do repositório; confiança: alta.

## D-003 [2026-11-17] Automação mínima: dois hooks
- Decisão: `SessionStart` mostra o estado da memória e guarda o commit inicial; `Stop` pede revisão uma única vez por sessão, só se houve mudança no projeto sem mudança na memória. A consolidação em si é feita pelo Claude seguindo a skill `salvar-memoria`.
- Justificativa: um hook de comando não lê a conversa de forma confiável nem resume conteúdo; quem pode decidir o que é durável é o modelo. `SessionEnd` não pode pedir nada ao Claude e, na nuvem, o container pode ser recolhido sem evento.
- Alternativas: gravar transcrições inteiras (crescimento ilimitado, risco de vazar dados num repositório público); lembrete a cada resposta (ruído).
- Status: vigente. Origem: análise da documentação de hooks e do ambiente; confiança: alta.
