---
name: pipeline-artigo-abnt
description: Orquestra o pipeline multiagente de produção de artigo científico ABNT (Revisor -> Sintetizador -> Arquiteto -> Redator + Validação de Coerência em paralelo -> Humanização -> .docx). Use quando o usuário fornecer fontes e um tema e pedir um artigo/minuta ABNT construído por etapas, ou pedir explicitamente para "rodar o pipeline ABNT".
---

Este pipeline usa 5 subagentes já definidos em `.claude/agents/`:
`agente-revisor`, `agente-sintetizador`, `agente-arquiteto`, `agente-redator`, `agente-validador-coerencia`.
As duas últimas etapas (Humanização e geração de `.docx`) não são subagentes — são skills já instaladas neste ambiente, acionadas pelo Skill tool.

## Fluxo

```
[Entrada: Fontes e Tema]
       │
       ▼
[Etapa 1: agente-revisor] ──> Matriz de Fichamento
       │
       ▼
[Etapa 2: agente-sintetizador] ──> Debate Teórico
       │
       ▼
[Etapa 3: agente-arquiteto] ──> Esqueleto ABNT Mapeado
       │
       ├─────────────────────────────┐
       ▼                             ▼
[Etapa 4: agente-redator]   [agente-validador-coerencia]
       │                             │
       └─────────────┬───────────────┘
                      ▼
        [Consolidação: Minuta + relatório de coerência]
                      │
                      ▼
      [Etapa 5: Humanização — skill rewrite-human ou human]
                      │
                      ▼
        [Etapa 6: Geração de .docx — skill docx]
                      │
                      ▼
           [Saída: artigo em .docx, estilo humanizado]
```

## Como executar

1. **Pré-condição**: confirme que você tem Fontes (arquivos, links ou texto) e um Tema/pergunta de pesquisa. Sem isso, pergunte ao usuário antes de iniciar — não invente fontes.
2. **Etapas 1→2→3 são sequenciais** (cada uma depende do output da anterior). Chame-as em foreground, uma de cada vez, via Agent tool, passando explicitamente o output da etapa anterior como entrada da próxima.
3. **Etapa 4 (agente-redator) e Validação de Coerência (agente-validador-coerencia) partem do mesmo Esqueleto ABNT Mapeado (saída da Etapa 3) e podem rodar simultaneamente** — dispare as duas chamadas ao Agent tool no mesmo turno (dois `Agent` invocations em paralelo), em vez de uma depois da outra.
4. **Consolidação**: depois que ambas retornarem, combine a minuta do Redator com os achados do Validador. Se houver achados **bloqueantes**, não avance para a Humanização — volte ao Arquiteto ou Redator para corrigir, e deixe isso explícito ao usuário. Só prossiga para a Etapa 5 com uma minuta sem achados bloqueantes pendentes.
5. **Etapa 5 — Humanização**: invoque a skill `anthropic-skills:rewrite-human` (ou `anthropic-skills:human`, se o usuário pedir especificamente o comando `/human`) sobre a prosa da minuta consolidada.
   - **Escopo estrito**: a humanização só pode alterar estilo (vocabulário, ritmo, estrutura sintética, transições) — nunca conteúdo, dado, citação, número de item normativo ou referência bibliográfica. Se a skill de humanização reescrever uma citação ou uma paráfrase de fonte, confira depois que o sentido e a atribuição não mudaram.
   - Preserve intactos os avisos de rastreabilidade herdados do Esqueleto (citações não conferidas, ADPF 1.068 em estágio incerto, Silva/B3 com autoria a confirmar, Bloco E/Xavier não citável) — eles são metadado do processo, não prosa do artigo, e não devem ser "humanizados" para dentro do texto nem apagados silenciosamente. Mantenha-os como nota separada para o autor.
   - Rode a humanização seção por seção (como o Redator escreveu), não o documento inteiro de uma vez, para manter controle sobre o que mudou.
6. **Etapa 6 — Geração de `.docx`**: só depois da Humanização, invoque a skill `anthropic-skills:docx` para produzir o arquivo Word final, com formatação ABNT básica (fonte, espaçamento, título, seções, referências). Entregue o `.docx` ao usuário (`SendUserFile`), não apenas o caminho do arquivo.

## O que não fazer
- Não pule etapas: a Matriz de Fichamento e o Debate Teórico existem para que o Redator nunca invente citação ou dado — sempre rastreável às fontes.
- Não rode o Redator antes do Arquiteto: ele precisa do esqueleto mapeado, não do debate bruto.
- Não trate achados "bloqueantes" do Validador como opcionais.
- Não gere o `.docx` a partir da minuta pré-humanização nem a partir de uma minuta com achados bloqueantes pendentes — a ordem Redator+Validador → Humanização → .docx é fixa.
- Não deixe a Humanização (Etapa 5) reescrever citações, dados, números de item normativo ou referências — isso não é "estilo", é conteúdo, e alterá-lo silenciosamente introduziria erro factual sob aparência de polimento.
- Ao final, lembre o usuário de que o `.docx` é um rascunho (marcado como tal pelo Redator) e que a revisão humana final é dele — alinhado ao princípio de autoria humana já declarado neste repositório (`Human-Written Declaration`, `anti-ai-style.md`). Humanizar o estilo não substitui essa revisão de conteúdo.
