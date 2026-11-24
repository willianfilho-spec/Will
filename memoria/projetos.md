# Projetos

Atualizado em: 2026-11-24
Um bloco por projeto: objetivo, local, estado, próximos passos. Estado vem de evidência (commit, teste, README); quando não houver, dizer "não verificado".

## Folha Clara (editor de PDF no navegador)
- Local: `editor-pdf/`; análise em `docs/editor-pdf/analise.md`; testes em `tools/verificar-fluxos/editor-pdf.json`.
- Objetivo: anotar, baixar e extrair texto/páginas/imagens de PDF sem enviar arquivo a servidor.
- [2026-11-17] Estado: entregue no PR #7 (commit 9fa2068, 2026-10-31). Próximos passos: não registrados — origem: git log e README; confiança: alta

## Editor do Guia SIGAA
- Local: `guia-sigaa-editor/`; publicação via `.github/workflows/pages.yml`.
- [2026-11-17] Estado: entregue no PR #5 (commit 490a335, 2026-10-27). Situação atual da publicação no GitHub Pages: não verificada — origem: git log; confiança: média

## Padronizador do Guia SIGAA
- Local: `padronizador-guia/` (app estática; reaproveita `editor-pdf/vendor/`); publicação em `/padronizador-guia/` via `pages.yml`.
- Objetivo: importar versão desconfigurada do guia (PDF ou PPTX), reconhecer os componentes do modelo 2026 (seção, caminho, passos, quadros, cartões, telas, tabelas) e gerar PDF novo no padrão.
- [2026-11-24] Estado: implementado e testado com Playwright no manual de 59 páginas e num PPTX desconfigurado de teste; branch `claude/brave-mayer-t6cn5d`, sem PR. Limitações: diagramas vetoriais não são capturados; leitura heurística exige revisão — origem: esta sessão; confiança: alta
- [2026-11-24] Testado com o PPTX real "Comentários Aplicados" (75 slides, feito no Google Slides): seções reconhecidas, FAQ interativo (26 respostas em slides ocultos) consolidado em 4 páginas, 26/26 referências de página conferidas no PDF gerado. Saída: 55 páginas — origem: esta sessão; confiança: alta

## Assistente de análise normativa
- Local: `assistente-analise-normativa.md` (prompt com formatos de saída por modo).
- [2026-11-17] Estado: adicionado em 2026-10-06; uso real não registrado — origem: git log; confiança: alta

## Ferramenta verificar-fluxos
- Local: `tools/verificar-fluxos/` (testes de fluxo com Playwright descritos em JSON), usada pelo agente `replicador-software`.
- [2026-11-17] Estado: em uso pelos projetos acima — origem: arquivos do repositório; confiança: média

## Sistema de memória persistente
- Local: `CLAUDE.md`, `memoria/`, `.claude/hooks/memoria.py`, `.claude/settings.json`, `.claude/skills/salvar-memoria/`.
- [2026-11-17] Estado: implementado, testado em sessões novas e incorporado à `main` (P-002 concluída). Próximo passo: nenhum obrigatório; acompanhar se o lembrete do hook Stop ajuda ou incomoda — origem: esta sessão; confiança: alta
