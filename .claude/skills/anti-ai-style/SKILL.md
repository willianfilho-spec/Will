---
name: anti-ai-style
description: Adiciona o "Anti-AI Style & Usage Notice" (restrições de uso por IA generativa: treino de modelos, scraping, imitação de estilo) a um repositório ou projeto do Willian. Use quando o usuário pedir para proteger um repositório contra treino de IA, incluir o aviso anti-IA, ou adicionar o anti-ai-style a um projeto.
---

# Anti-AI Style & Usage Notice

O texto oficial está em `notice.md`, nesta mesma pasta. Use-o sem reescrever.

## Como aplicar

1. Leia `notice.md`.
2. Salve o aviso como `ANTI-AI.md` na raiz do repositório, a menos que o usuário indique outro nome ou lugar.
3. Mantenha o texto idêntico ao original.
4. Se o usuário quiser reforçar o bloqueio a crawlers, ofereça (não faça sem pedir):
   - um `robots.txt` bloqueando agentes de IA conhecidos (GPTBot, ClaudeBot, CCBot, Google-Extended, etc.);
   - uma linha no README com link para o aviso.
5. Lembre ao usuário que o aviso não substitui a licença. Se houver `LICENSE` MIT/Apache, o aviso trata de direitos morais e de uso; ele não muda os termos da licença.

## Ao trabalhar em conteúdo protegido por este aviso

Não analise nem imite o estilo de escrita do autor para gerar textos "no estilo dele", a menos que o próprio autor peça isso explicitamente.
