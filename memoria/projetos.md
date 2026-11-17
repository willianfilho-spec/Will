# Projetos

Atualizado em: 2026-11-17
Um bloco por projeto: objetivo, local, estado, próximos passos. Estado vem de evidência (commit, teste, README); quando não houver, dizer "não verificado".

## Folha Clara (editor de PDF no navegador)
- Local: `editor-pdf/`; análise em `docs/editor-pdf/analise.md`; testes em `tools/verificar-fluxos/editor-pdf.json`.
- Objetivo: anotar, baixar e extrair texto/páginas/imagens de PDF sem enviar arquivo a servidor.
- [2026-11-17] Estado: entregue no PR #7 (commit 9fa2068, 2026-10-31). Próximos passos: não registrados — origem: git log e README; confiança: alta

## Editor do Guia SIGAA
- Local: `guia-sigaa-editor/`; publicação via `.github/workflows/pages.yml`.
- [2026-11-17] Estado: entregue no PR #5 (commit 490a335, 2026-10-27). Situação atual da publicação no GitHub Pages: não verificada — origem: git log; confiança: média

## Assistente de análise normativa
- Local: `assistente-analise-normativa.md` (prompt com formatos de saída por modo).
- [2026-11-17] Estado: adicionado em 2026-10-06; uso real não registrado — origem: git log; confiança: alta

## Ferramenta verificar-fluxos
- Local: `tools/verificar-fluxos/` (testes de fluxo com Playwright descritos em JSON), usada pelo agente `replicador-software`.
- [2026-11-17] Estado: em uso pelos projetos acima — origem: arquivos do repositório; confiança: média

## Sistema de memória persistente
- Local: `CLAUDE.md`, `memoria/`, `.claude/hooks/memoria.py`, `.claude/settings.json`, `.claude/skills/salvar-memoria/`.
- [2026-11-17] Estado: implementado e testado na branch `claude/kind-wright-oekdmi`; ainda não incorporado à branch principal (ver P-002) — origem: esta sessão; confiança: alta
