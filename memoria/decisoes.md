# Decisões

Atualizado em: 2026-11-28
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

## D-006 [2026-11-26] Assistente DIOAC publicado na íntegra no GitHub Pages
- Decisão: publicar o Assistente DIOAC v3 completo (base com minuta do Calendário 2027 e documentos internos) em `assistente-dioac/`, servido pelo GitHub Pages deste repositório público. Decidido pelo usuário após aviso explícito dos riscos.
- Justificativa: acesso por link público, sem login nem instalação.
- Alternativas: edição pública só com atos oficiais (recomendada e recusada); link privado no claude.ai; arquivo único local.
- Consequências: a base fica aberta e indexável. Substitui, para este app, a decisão de 25/11/2026 de mantê-lo fora do repositório. A política de D-002 continua valendo para `memoria/`.
- Status: vigente. Origem: pedido do usuário; confiança: alta.

## D-007 [2026-11-28] Graphify e plugin EGM instalados por script de setup do ambiente
- Decisão: instalar o Graphify (`uv tool install graphifyy` + `graphify install`) e o plugin Elephant-Goldfish Model (`egm@egm`, marketplace `google/elephant-goldfish-model`) por script de setup do ambiente de nuvem pessoal "computador", não por arquivos do repositório.
- Justificativa: os containers são descartáveis; o script reinstala as duas ferramentas em toda sessão nova sem alterar este repositório público.
- Alternativas: instalar a cada sessão manualmente; criar um ambiente novo.
- Consequências: comandos testados isoladamente nesta sessão (Graphify num projeto de exemplo, um revisor EGM num rascunho). O script completo não foi provado: só roda na próxima sessão com container novo. Conferir com `graphify --help` e `claude plugin list`. `/graphify .` e `graphify claude install` não foram rodados neste repositório.
- Status: vigente. Origem: pedido do usuário; confiança: alta.
