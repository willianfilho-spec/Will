# Padronizador do Guia SIGAA

App web estática que recebe uma versão **desconfigurada** do Guia SIGAA (PDF ou PPTX), reconhece o conteúdo e gera um **PDF novo no padrão gráfico** do *Manual do Coordenador SIGAA 2026* (DIOAC/PROEN/UFMA).

Todo o processamento acontece no navegador: nenhum arquivo é enviado para servidor.

## Executar

Precisa ser servida por HTTP a partir da **raiz do repositório**, porque reaproveita o pdf.js e o pdf-lib de `editor-pdf/vendor/`:

```bash
python3 -m http.server 8080   # na raiz do repositório
# abra http://localhost:8080/padronizador-guia/
```

No GitHub Pages fica em `/padronizador-guia/` (ver `.github/workflows/pages.yml`).

## Fluxo

1. **Importar PDF ou PPTX** (botão ou arrastar o arquivo para a janela).
2. A leitura automática monta cada página com os componentes do modelo. Páginas com dúvida aparecem com ⚠ e um ponto amarelo/vermelho na lista.
3. Revise no editor do meio; a prévia à direita mostra a página já padronizada. "Comparar com o original" põe as duas lado a lado (só para PDF).
4. **Baixar PDF padronizado.** "Salvar projeto" guarda um `.json` para continuar depois; o último projeto também fica salvo neste navegador.

## O que é padronizado

Tudo é redesenhado a partir do conteúdo, não remendado sobre o original:

| Elemento | Padrão aplicado |
|---|---|
| Página | A4 retrato, margens de 36 pt, fonte Helvetica/Arial |
| Cabeçalho | faixas dourada/vinho/turquesa, "GUIA SIGAA", selo FAQ, logo dos 60 anos à direita |
| Rodapé | barra vinho com "DIOAC \| PROEN \| UFMA", "(SIGAA, 2026)" e "Sumário N" com **numeração refeita** |
| Seção e título | seção em caixa alta na cor da área (Dados cadastrais = vinho, Regularização = turquesa, Turmas = dourado, Matrículas = verde, Atividades = vermelho, Consultas = cinza) |
| Caminho no SIGAA | caixa bege, setas uniformes (`>` ou `->` digitados viram →) |
| Como fazer | passos numerados em círculo vinho; quadros de observação/regulamentação ficam ao lado, como no modelo |
| Quadros | Observação, Regulamentação, Atenção, Destaque, cada um com cor e barra próprias |
| Cartões | grade de 2 colunas com barra colorida (lateral ou no topo) |
| Telas do SIGAA | imagem na largura útil, rótulo e legenda "Fonte: (SIGAA, 2026)." |
| Paginação | conteúdo que não cabe continua na página seguinte com "(continuação)"; imagens encolhem até 60% antes de mudar de página |

## Tratamentos específicos de PPTX

- **Slides ocultos** entram marcados como "Não incluir", com aviso. Desmarque se devem ir para o PDF.
- **FAQ interativo** (slides de navegação com abas, botão "Voltar ao FAQ" e lista de perguntas repetida em cada slide) é consolidado em páginas lineares por categoria, em ordem numérica. O índice interativo fica fora do PDF, com aviso.
- **Referências "Ver no manual · p. N"** que eram links para outro slide viram `{{pag:N}}` e são recalculadas na geração: se páginas anteriores se desdobrarem, o número acompanha. Uma referência para página excluída aparece como "?" e gera aviso.
- **Números soltos** (marcadores de passo fora do lugar, sem nada na mesma linha e fora de "Como fazer") são removidos, com aviso.
- Página sem seção nem título logo após um procedimento herda a seção e o título dele (continuação).

## Limitações conhecidas

- **A leitura é heurística.** Ela reconhece os rótulos do modelo (Caminho no SIGAA, Como fazer, Quando usar, Observação, Regulamentação, Atenção, Tela do SIGAA…) e a posição dos elementos. Layouts muito diferentes do modelo, diagramas feitos com formas e tabelas desenhadas em PDF viram texto ou cartões e precisam de revisão.
- **PPTX:** posições vêm das caixas de texto; textos herdados do layout mestre sem posição própria vão para o fim da ordem. Imagens EMF/WMF não são lidas (há aviso). O PPTX não gera a imagem "original" da página, então "Manter como no original" e "Comparar" só existem para PDF.
- **Diagramas desenhados com formas vetoriais** (setas e caixas do próprio PowerPoint, não imagens) não são capturados. Só imagens de fato (prints, fluxos exportados como figura) entram. Nesses casos, troque a imagem no bloco ou use "Manter como no original" na página.
- Recortes de imagem praticamente de uma cor só (máscaras, retângulos brancos) são descartados de propósito; se a tela sumir, o bloco "Tela do SIGAA" fica com "[sem imagem]" para você completar.
- Quando três ou mais colunas de títulos em negrito aparecem lado a lado, o conteúdo vira tabela. Funciona bem para tabelas de verdade (ex.: Registro do ENADE), mas fluxos em colunas também podem virar tabela e pedir ajuste manual.
- PDF digitalizado (sem texto) não tem o que reconhecer: use "Manter como no original".
- Texto com caracteres fora do conjunto Latin-1 (emoji etc.) sai como `?` no PDF.
- A saída é PDF. Não gera PPTX.
