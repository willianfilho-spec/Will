# Folha Clara — editar e extrair PDF no navegador

App web estática. Abre um PDF local, permite anotar e baixar o PDF com as marcas, e extrai texto, páginas e imagens. Todo o processamento acontece no navegador: nenhum arquivo é enviado para servidor.

## Executar

Precisa ser servida por HTTP (módulos ES e o worker do pdf.js não funcionam via `file://`):

```bash
npx http-server editor-pdf -p 8080   # ou: python3 -m http.server -d editor-pdf 8080
# abra http://localhost:8080
```

Testes:

```bash
node tools/verificar-fluxos/verificar.mjs tools/verificar-fluxos/editor-pdf.json          # 12 fluxos gerais
node tools/verificar-fluxos/verificar.mjs tools/verificar-fluxos/editor-pdf-edicao.json   # 11 fluxos de Editar texto/OCR
node tools/verificar-fluxos/fixtures/gerar-fixtures-edicao.mjs                            # regera as fixtures
```

## Funções

- **Editar texto** (ferramenta principal, atalho X): edita o texto que já existe no PDF.
  1. Passe o mouse: as linhas detectadas ficam destacadas. Clique numa linha: um campo abre **no lugar**, já preenchido, com o mesmo tamanho aproximado, a mesma fonte (quando é Helvetica/Times/Courier; senão Noto Sans), negrito e cor estimados.
  2. Enter (ou clicar fora) confirma, Esc cancela, Shift+Enter quebra linha. Arraste a borda tracejada ou a bolinha para mover o texto.
  3. Ao confirmar, cria-se uma anotação "edição": cobre o texto antigo com o **fundo amostrado ao redor** (cor única, degradê vertical ou colunas de degradê; não é branco) e desenha o novo. Mover/apagar/desfazer funcionam como nas outras; mover leva só o texto, a cobertura fica onde estava.
  4. **PDF com camada de texto**: as linhas vêm do pdf.js. **PDF só de imagem** (ex.: cartaz exportado de ferramenta de design): clique em "Reconhecer texto desta página" (OCR, roda só neste navegador, nunca ao abrir, com barra de progresso). **O OCR pode errar** (acentos, letras parecidas) e falha com fontes decorativas e fundos de foto: revise o texto. Se faltar uma linha, arraste um retângulo sobre ela (mouse): o app mede cor, tamanho e negrito pelos pixels.
  5. Texto novo mais largo que a página tem o tamanho reduzido automaticamente (aviso na tela).
- **Texto, Marca-texto, Caneta, Retângulo, Elipse, Linha, Imagem** (PNG/JPEG/WebP/GIF) e **Cobrir e reescrever** (cobre uma área que você desenha, também com o fundo amostrado). Fonte (Noto Sans, Helvetica, Times, Courier), negrito, itálico, alinhamento, tamanho (padrão proporcional à largura da página) e atalhos de cor (vinho, dourado, preto, branco) além do seletor. Texto nasce preto. A caixa de digitação não tem fundo: é só um contorno fino e o texto já aparece como ficará.
- **Mover/apagar**: ferramenta Mover, botão Apagar ou Delete. Desfazer com Ctrl+Z. Duplo clique num texto o reabre.
- **Baixar PDF**: as anotações são desenhadas no conteúdo da página ("achatadas"). Texto novo em Noto Sans é embutido (subconjunto) com fontkit.
- **Remover de vez o texto antigo** (aparece ao baixar, quando há edição ou "cobrir"): **cobrir NÃO apaga o texto original do arquivo.** Se o PDF tem camada de texto, o texto antigo continua lá e pode ser copiado em qualquer leitor. Marcando a opção, só as páginas editadas são rasterizadas (JPEG, até 3x, ~216 dpi) e substituem as originais: o texto antigo deixa de existir no arquivo, mas essas páginas perdem texto selecionável, links e o arquivo pode crescer. Sem a opção, um aviso lembra disso.
- **Extrair**: texto (por página e completo, copiar e baixar `.txt`), novo PDF com as páginas escolhidas (com ou sem anotações), imagens embutidas (decodificadas e salvas como PNG) e página inteira renderizada como PNG.
- **Sessão**: o último PDF e as anotações ficam no IndexedDB deste navegador e voltam depois de recarregar. "Fechar" apaga a sessão. O resultado do OCR não é guardado (refazer leva alguns segundos).

## Como o fundo e a cor são escolhidos

Documentado em `texto.js`. Fundo: mediana por canal dos pixels do anel de 3 px **fora** da caixa (cima e baixo primeiro, porque as laterais podem cortar letras; as laterais só refinam o que concordar). Se o fundo varia na vertical, usa faixas (degradê); se varia na horizontal, usa até 24 colunas, cada uma com seu degradê vertical. Cor do texto: média dos ~4% de pixels mais distantes do fundo dentro da caixa. A caixa é estendida pelos pixels de tinta contíguos (acentos, cedilha) antes de amostrar de novo.

## Tamanho e OCR

O OCR (tesseract.js 7, núcleo WebAssembly SIMD, dados `por` + `eng` "best_int") fica em `vendor/tesseract/`: **8,4 MB** (3,9 MB do núcleo, 4,3 MB de idiomas, 0,2 MB de scripts). Junto com fontkit (0,76 MB) e Noto Sans (0,07 MB) a adição total é **9,3 MB**; `vendor/` inteiro tem 13,5 MB. Esses arquivos só são baixados quando se clica em "Reconhecer texto". Exige navegador com WebAssembly SIMD (Chrome 91+, Firefox 89+, Safari 16.4+).

## Limitações conhecidas

- **Cobrir não apaga** (ver acima). Só a opção "Remover de vez" remove o texto antigo do arquivo.
- **Fonte decorativa não é reproduzida.** O app não identifica a fonte pelos pixels: o texto novo sai em Noto Sans (ou na fonte padrão do PDF, quando ela é conhecida). Um cartaz com fonte estilizada ficará com letras diferentes das vizinhas.
- **O OCR erra**: perde acentos (no teste, "ATENÇÃO" voltou "ATENCAO"), troca letras parecidas e falha com fontes decorativas, itálico ou fundo de foto (nesses casos use o retângulo).
- **Fundo de foto ou textura**: a cobertura é um degradê amostrado nas bordas, sem o grão e os detalhes da imagem; em fundo complexo fica um retalho visível. Fundo liso ou em degradê simples fica bom.
- O retângulo à mão exige arrastar com o mouse; em tela de toque o arraste vertical rola a página. Linhas inclinadas (mais de 4°) não são detectadas.
- Fontes: Noto Sans embutida cobre latim estendido. Gregos, cirílicos, CJK e emoji viram `?`. Helvetica/Times/Courier usam WinAnsi.
- Não redimensiona anotações por alças, não tem zoom e não abre PDFs com senha.
- Imagens JPEG 2000/JBIG2 dentro do PDF podem não aparecer (os módulos WASM do pdf.js não foram incluídos).

Bibliotecas: ver `vendor/LICENCAS.md`.
