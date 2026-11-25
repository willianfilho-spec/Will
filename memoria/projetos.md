# Projetos

Atualizado em: 2026-11-25
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
- [2026-11-17] Estado: implementado, testado em sessões novas e incorporado à `main` (P-002 concluída). Próximo passo: nenhum obrigatório; acompanhar se o lembrete do hook Stop ajuda ou incomoda — origem: esta sessão; confiança: alta

## Assistente DIOAC (busca local na base normativa da graduação)
- Local: fora deste repositório, por decisão do usuário em 2026-11-25 (a base inclui documentos internos e o repositório é público). Entregue como pacote zip na sessão; não há cópia versionada.
- [2026-11-25] Estado: v2 completado (pasta vendor com JSZip 3.10.1 e pdf.js 3.11.174), visual revisado e base na versão 2026-11-25.6; busca prioriza o ano/semestre citado; 13 testes de navegador aprovados (Playwright) — origem: esta sessão; confiança: alta
- [2026-11-25] Regra de conteúdo: o Manual do Coordenador SIGAA 2026 é a única referência para o Portal da Coordenação; o guia de 2023 saiu da base. Fontes secundárias entram como "material de apoio", com nota de conferência quando a citação não bate com a norma — origem: pedido do usuário; confiança: alta
- [2026-11-25] Calendário 2027 entrou como minuta sem número; substituir quando a resolução for publicada — origem: arquivo enviado; confiança: alta
