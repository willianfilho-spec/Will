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

## D-006 [2026-11-18] Conciliador usa só dados sintéticos no repositório
- Decisão: arquivos reais de clientes (extratos, planos, lotes, pareceres) ficam fora do git; testes e exemplos usam dados inventados. A pasta `data/` do app está no `.gitignore`.
- Justificativa: o repositório é público (D-002) e os arquivos enviados têm dados contábeis de clientes.
- Alternativas: anonimizar os arquivos reais (dá trabalho e há risco de sobrar dado identificável).
- Consequências: o leiaute do Fortes foi copiado dos arquivos reais, mas a validação final precisa ser feita localmente, com arquivos reais fora do repositório.
- Status: vigente. Origem: esta sessão; confiança: alta.

## D-007 [2026-11-18] Item de instalação real só é aprovado com evidência registrada no app
- Decisão: os itens H1 a H5 da P-004 só viram "aprovado" por administrador, com evidência anexada (SHA-256) e as condições conferidas em código; teste automatizado nunca os aprova. O registro é só de inclusão. O app mostra aviso de integração não homologada até os cinco estarem aprovados.
- Justificativa: pedido do usuário (homologação P-004) e preferência já registrada de não declarar sucesso sem evidência.
- Alternativas: marcar como concluído pelos testes sintéticos (descartada: não prova compatibilidade com o Fortes).
- Consequências: a P-004 só sai de `pendencias.md` quando o relatório mostrar H1 a H5 aprovados.
- Status: vigente. Origem: pedido do usuário; confiança: alta.

## D-008 [2026-11-18] Web app em FastAPI para uso externo; Streamlit fica como modo local
- Decisão: a interface para equipe e clientes externos é um web app FastAPI (`conciliador_fortes/web/`), com sessões no servidor, CSRF, 2FA TOTP obrigatório para a equipe, bloqueio de login, CSP restritiva e portal do cliente. O Streamlit continua só como modo local legado.
- Justificativa: o Streamlit não oferece controle de sessão, CSRF, limite de requisições nem cabeçalhos de segurança adequados para expor a clientes.
- Alternativas: endurecer o Streamlit (descartada: sem controle sobre o ciclo HTTP).
- Consequências: HTTPS depende de proxy na implantação; a criptografia de arquivos exige `CONCILIADOR_CHAVE`; o banco SQLite continua sem criptografia própria (usar criptografia de disco); nenhum pentest independente foi feito.
- Status: vigente. Origem: pedido do usuário (uso interno e externo); confiança: alta.

## D-009 [2026-11-18] Identidade do operador inclui o id; lançamentos manuais sempre exigem segunda confirmação
- Decisão: toda ação grava `Nome #id` (a segregação de função compara esse valor, não só o nome). Lançamento sem conta de banco (provisão, reclassificação, ajuste) é criado por uma pessoa e confirmado por outra, sem exceção de valor.
- Justificativa: homônimos entre usuários externos quebrariam a segregação; lançamento manual não tem extrato como evidência.
- Status: vigente. Origem: revisão de projeto nesta sessão; confiança: alta.

## D-010 [2026-11-18] MVP entregue como pacote Windows local (Python embutido), não como serviço hospedado
- Decisão: o MVP de teste vai num zip que roda no computador de cada testador (`scripts/montar_pacote.py`), com Python 3.12 do NuGet e dependências dentro; modo de teste local (sem HTTPS, sem 2FA, dados de demonstração, arquivos cifrados com chave em `dados/chave.key`). Opção `--rede` para uso em rede interna.
- Justificativa: pedido do usuário (apresentar pronto para testarem; não rodar no Claude). `python.org` é inacessível do ambiente de build; o NuGet serve o mesmo Python.
- Alternativas: instalar Python na máquina de cada pessoa (mais atrito); hospedar (exige HTTPS e decisões de LGPD ainda abertas).
- Consequências: execução em Windows não verificada (build feito em Linux); o zip não vai para o git; este pacote não é a implantação para clientes externos (P-005 continua aberta).
- Status: vigente. Origem: pedido do usuário; confiança: alta.

