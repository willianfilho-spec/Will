# Pendências

Atualizado em: 2026-11-18
Só itens abertos. Ao concluir, mover uma linha-resumo para `historico.md` e apagar daqui.


- [2026-11-18] P-004 Confirmar os perfis numa sessão aberta só com este repositório. Na sessão com os três repositórios, a lista mostrou `tela`, `testes` e `documentacao`, mas na versão do dataset: perfis de mesmo nome colidem e só um é carregado. Se a colisão incomodar, avaliar nomes com sufixo por repositório — origem: lista de agentes da sessão; confiança: alta
- [2026-11-18] P-005 Incorporar à `main` os branches `claude/exciting-lovelace-c7qn2h` dos três repositórios. Sem isso, sessões abertas na `main` não veem o fluxo de orquestração — origem: esta sessão; confiança: alta
- [2026-11-18] P-006 Decidir a tensão entre a `Human-Written Declaration` e a documentação técnica escrita com IA: o perfil `documentacao` escreveria READMEs fora da exceção de D-005, e `editor-pdf/README.md`, `tools/verificar-fluxos/README.md` e `docs/editor-pdf/analise.md` já foram coescritos pelo Claude no PR #7. Opções: ampliar a exceção ou limitar o perfil a propor textos para o usuário reescrever — origem: leitura da declaração e do commit 9fa2068; confiança: alta
- [2026-11-18] P-007 No repositório privado do laudo de viabilidade, rodar `python gerar_laudo.py` para confirmar o comando documentado; a execução foi bloqueada pelo classificador de permissões nesta sessão (só `py_compile` passou) — origem: esta sessão; confiança: alta
