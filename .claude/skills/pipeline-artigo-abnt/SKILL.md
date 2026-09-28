---
name: pipeline-artigo-abnt
description: Orquestra o pipeline multiagente de produção de artigo científico ABNT (Revisor -> Sintetizador -> Arquiteto -> Redator + Validação de Coerência em paralelo -> Minuta). Use quando o usuário fornecer fontes e um tema e pedir um artigo/minuta ABNT construído por etapas, ou pedir explicitamente para "rodar o pipeline ABNT".
---

Este pipeline usa 5 subagentes já definidos em `.claude/agents/`:
`agente-revisor`, `agente-sintetizador`, `agente-arquiteto`, `agente-redator`, `agente-validador-coerencia`.

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
        [Saída: Minuta do Artigo ABNT + relatório de coerência]
```

## Como executar

1. **Pré-condição**: confirme que você tem Fontes (arquivos, links ou texto) e um Tema/pergunta de pesquisa. Sem isso, pergunte ao usuário antes de iniciar — não invente fontes.
2. **Etapas 1→2→3 são sequenciais** (cada uma depende do output da anterior). Chame-as em foreground, uma de cada vez, via Agent tool, passando explicitamente o output da etapa anterior como entrada da próxima.
3. **Etapa 4 (agente-redator) e Validação de Coerência (agente-validador-coerencia) partem do mesmo Esqueleto ABNT Mapeado (saída da Etapa 3) e podem rodar simultaneamente** — dispare as duas chamadas ao Agent tool no mesmo turno (dois `Agent` invocations em paralelo), em vez de uma depois da outra.
4. **Consolidação final**: depois que ambas retornarem, combine a minuta do Redator com os achados do Validador. Se houver achados **bloqueantes**, não apresente a minuta como final — volte ao Arquiteto ou Redator para corrigir antes de entregar, e deixe isso explícito ao usuário.

## O que não fazer
- Não pule etapas: a Matriz de Fichamento e o Debate Teórico existem para que o Redator nunca invente citação ou dado — sempre rastreável às fontes.
- Não rode o Redator antes do Arquiteto: ele precisa do esqueleto mapeado, não do debate bruto.
- Não trate achados "bloqueantes" do Validador como opcionais.
- Ao final, lembre o usuário de que a minuta é um rascunho (marcado como tal pelo Redator) e que a revisão humana final é dele — alinhado ao princípio de autoria humana já declarado neste repositório (`Human-Written Declaration`, `anti-ai-style.md`).
