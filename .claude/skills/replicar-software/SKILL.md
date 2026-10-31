---
name: replicar-software
description: Analisa um software de referência (link, prints, vídeos ou documentação), mapeia telas, fluxos e regras, e orienta a construção de uma versão própria funcional, testada no navegador com Playwright e registrada no Git. Use quando o pedido for "recriar", "replicar", "fazer uma alternativa a", "clonar o fluxo de" ou "analisar sem programar" um software.
---

# Replicar Software

Skill de método. Ela não programa sozinha: define **como analisar**, **o que construir primeiro** e **quando a entrega pode ser considerada pronta**.

## 1. Escolha o modo

| Modo | Pedido típico | Entrega |
|---|---|---|
| **A — Recriar por link** | "recrie o X, disponível em [link]" | App funcional + relatório |
| **B — Construir por prints/vídeos** | "construa a partir dos prints anexados" | App fiel ao layout + hipóteses explícitas |
| **C — Alternativa própria** | "crie uma alternativa ao X para [público]" | App com identidade visual própria + melhorias |
| **D — Só análise** | "analise sem programar" | Mapa funcional + stack + custos + plano por etapas. **Não escreva código.** |

Se faltarem dados essenciais (referência, funcionalidades prioritárias ou plataforma alvo), pergunte uma vez, em bloco. Se o usuário não responder, adote o padrão: **web, arquivo estático ou app leve, dados no navegador**, e declare isso como hipótese.

## 2. Análise da referência (todos os modos)

Produza o **Mapa Funcional** em `docs/<projeto>/analise.md`:

1. **Telas** — nome, objetivo, componentes visíveis, navegação de entrada e saída.
2. **Fluxos principais** — no máximo 5, em passos numerados (ator → ação → resultado esperado).
3. **Regras de negócio** — validações, cálculos, estados, permissões.
4. **Dados** — entidades, campos, onde ficam armazenados.
5. **Integrações** — APIs, login, pagamento, e-mail etc.

Cada item recebe uma etiqueta de evidência:

- `[OBSERVADO]` — visto no link, print, vídeo ou documentação (cite a fonte: URL, nome do print, minuto do vídeo).
- `[HIPÓTESE]` — inferido; explique o porquê em uma linha.
- `[INVESTIGAR]` — não dá para saber sem acesso adicional (conta, backend, contrato de API).

Nunca apresente hipótese como fato observado.

## 3. Escopo da primeira versão

- Implemente **por completo** o fluxo principal antes de qualquer fluxo secundário.
- Integrações externas (pagamento, e-mail, APIs pagas) entram **simuladas** (mock) na v1, marcadas como `SIMULADO` na interface ou no código.
- Persistência: `localStorage`/IndexedDB para apps estáticos; SQLite ou JSON local quando houver servidor. Só proponha banco gerenciado se o pedido exigir multiusuário.
- Stack padrão (troque só com justificativa): HTML+CSS+JS puro para apps pequenos; Vite + React para apps com várias telas e estado complexo; Electron/Tauri para Windows; PWA antes de app nativo para celular.

## 4. Limites legais e éticos

- Replique **funcionalidade e fluxo**, não marca. Não copie logotipo, nome comercial, textos protegidos, ícones proprietários nem código-fonte da referência.
- No modo C, a identidade visual deve ser **própria** (paleta, tipografia e nome diferentes).
- Não contorne login, paywall, DRM ou termos de uso da referência para analisá-la. Se algo só é acessível assim, marque `[INVESTIGAR]`.

## 5. Critérios de funcionamento (Definition of Done)

A entrega só está pronta quando **todos** os itens abaixo forem verdadeiros (exceto modo D):

1. O app abre sem erros no console do navegador.
2. Cada fluxo principal do Mapa Funcional tem um teste Playwright correspondente em `tools/verificar-fluxos/` (ou em `tests/` do projeto) e **passa**.
3. Existe ao menos um teste de **persistência** (criar dado → recarregar a página → dado continua lá) quando o app armazena dados.
4. Existe ao menos um teste em **viewport de celular** (390×844) quando o alvo é web ou celular.
5. Capturas de tela de cada fluxo foram salvas e revisadas visualmente.
6. As mudanças foram commitadas com mensagens descritivas.
7. O relatório final (seção 6) foi entregue.

Se um critério não puder ser cumprido, diga qual e por quê. Não declare "pronto" com teste falhando.

## 6. Relatório final (obrigatório)

```
## Como executar
<comandos>

## Funciona (testado)
- <fluxo> — teste <arquivo/nome> ✅

## Simulado
- <integração> — como foi simulada

## Pendente / [INVESTIGAR]
- <item> — o que falta para resolver

## Hipóteses adotadas
- <hipótese> — motivo

## Diferenças em relação à referência
- <diferença>
```

No modo D, o relatório é substituído por: mapa funcional, stack recomendada com justificativa, dificuldades e dependências, estimativa de custos recorrentes (hospedagem, APIs, licenças — com faixa e fonte, ou "não estimado"), e plano de implementação em etapas com critério de saída de cada etapa.
