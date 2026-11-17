---
name: salvar-memoria
description: Consolida na pasta memoria/ o que esta sessão produziu de durável (decisões, estado de projetos, pendências, preferências declaradas, soluções validadas). Use ao encerrar um trabalho, quando o hook Stop pedir revisão da memória, ou quando o usuário disser "salve na memória", "lembre disso", "atualize a memória".
---

# Salvar memória

Objetivo: atualizar `memoria/` com o mínimo necessário, sem duplicar, sem inventar e sem expor dados num repositório público.

## Procedimento

1. **Liste candidatos** a partir do que aconteceu nesta sessão. Entra só o que for durável:
   - decisão definitiva → `decisoes.md` (novo `D-XXX` com justificativa, alternativas, consequências, status);
   - mudança de estado de projeto, com evidência (commit, teste, PR) → `projetos.md`;
   - tarefa interrompida, compromisso, pergunta aberta → `pendencias.md` (novo `P-XXX`);
   - preferência que o usuário declarou explicitamente → `preferencias.md`;
   - erro recorrente e a correção validada → `decisoes.md` ou `projetos.md` do projeto;
   - contexto profissional útil e já público → `usuario.md`.
   Não entra: conversa, tentativa descartada, suposição, informação transitória.
2. **Compare com a memória atual.** Leia o arquivo de destino antes de escrever. Se já existe, atualize a linha (e a data); não acrescente outra igual.
3. **Contradição**: não sobrescreva em silêncio. Decisão antiga vira `Status: substituída por D-XXX`; em preferências e projetos, mantenha a linha antiga com `(substituída em AAAA-MM-DD: motivo)` até a próxima compactação.
4. **Pendência concluída**: apague de `pendencias.md` e adicione uma linha em `historico.md`.
5. **Formato**: `- [AAAA-MM-DD] texto — origem: …; confiança: alta|média|baixa`. Atualize a linha `Atualizado em:` dos arquivos alterados.
6. **Privacidade**: nada de e-mail, telefone, CPF, endereço, credencial, token, dado de saúde ou informação sobre terceiros. O repositório é público.
7. **Verifique**: `python3 .claude/hooks/memoria.py verificar`. Corrija todo ERRO; trate avisos de tamanho compactando (resumir itens antigos, nunca apagar decisões).
8. **Commit e push** só dos arquivos de `memoria/` alterados, com mensagem `memoria: <resumo>`. Sem push, a memória se perde quando o container for recolhido.
9. **Informe ao usuário** quais arquivos mudaram e o que foi registrado, em poucas linhas. Se nada merecia registro, diga isso.
