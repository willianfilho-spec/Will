# Bibliotecas de terceiros (vendorizadas)

Cópias sem alteração dos arquivos `dist`, obtidas do registro npm em 2026-10-31. Nada é carregado de CDN: tudo roda offline.

| Pasta | Pacote | Versão | Licença | Arquivos |
|---|---|---|---|---|
| `pdfjs/` | [pdfjs-dist](https://github.com/mozilla/pdf.js) (Mozilla) | 6.4.299 | Apache-2.0 (`pdfjs/LICENSE`) | `pdf.min.mjs`, `pdf.worker.min.mjs`, `standard_fonts/` (licenças Foxit e Liberation na própria pasta), `cmaps/` |
| `pdf-lib/` | [pdf-lib](https://github.com/Hopding/pdf-lib) | 1.17.1 | MIT (`pdf-lib/LICENSE.md`) | `pdf-lib.min.js` (UMD, expõe `window.PDFLib`) |
| `fontkit/` | [@pdf-lib/fontkit](https://github.com/Hopding/fontkit) | 1.1.1 | MIT | `fontkit.umd.min.js` (UMD, expõe `window.fontkit`; permite embutir fontes TrueType/WOFF no PDF) |
| `fontes/` | [Noto Sans](https://github.com/notofonts/latin-greek-cyrillic), via [@fontsource/noto-sans](https://fontsource.org/fonts/noto-sans) | 5.3.0 | SIL Open Font License 1.1 (`fontes/OFL.txt`) | 4 arquivos `.woff` (subconjunto latino, 400/700, normal/itálico) |
| `tesseract/` | [tesseract.js](https://github.com/naptha/tesseract.js) | 7.0.0 | Apache-2.0 (`tesseract/LICENSE-tesseract.js.md`) | `tesseract.esm.min.js`, `worker.min.js` |
| `tesseract/` | [tesseract.js-core](https://github.com/naptha/tesseract.js-core) (Tesseract OCR compilado para WebAssembly) | 7.0.0 | Apache-2.0 (`tesseract/LICENSE-tesseract.js-core.txt`) | `tesseract-core-simd-lstm.wasm.js` (WASM embutido no JS) |
| `tesseract/lang/` | [@tesseract.js-data/por](https://github.com/naptha/tessdata) e `/eng` (modelos `tessdata_best`, quantizados em inteiros, variante `4.0.0_best_int`) | 4.0.0 | Apache-2.0 (modelos do projeto [tesseract-ocr/tessdata_best](https://github.com/tesseract-ocr/tessdata_best); o `package.json` do pacote npm declara MIT para o empacotamento) | `por.traineddata.gz`, `eng.traineddata.gz` |

## Tamanho do pacote de OCR

`vendor/tesseract/` = 8,4 MB (núcleo 3,9 MB, `por` 1,4 MB, `eng` 2,9 MB, scripts 0,2 MB); `vendor/fontkit/` = 0,76 MB; `vendor/fontes/` = 0,07 MB. O OCR só é baixado quando o usuário pede "Reconhecer texto desta página": o app não toca nesses arquivos ao abrir.

## Decisões

- **Núcleo do OCR**: só a variante `simd-lstm` (suportada por navegadores desde 2021: Chrome 91, Firefox 89, Safari 16.4). Navegadores sem WebAssembly SIMD não conseguem rodar o OCR (o resto do app funciona). O `tesseract.js` aceita um `corePath` terminado em `.js` e carrega esse arquivo direto, sem consultar CDN.
- **Dados de idioma**: `best_int` (modelos "best" quantizados) em vez de "fast": ficam pequenos (1,4 MB + 2,9 MB) e reconhecem melhor que o "fast" original. Só LSTM (`oem=1`).
- **Fonte Unicode**: Noto Sans (OFL) cobre latim estendido (acentos do português, aspas tipográficas, €, •). Gregos, cirílicos, CJK e emoji não: viram `?` no PDF baixado.

Para atualizar: `npm i pdfjs-dist pdf-lib @pdf-lib/fontkit tesseract.js tesseract.js-core @tesseract.js-data/por @tesseract.js-data/eng @fontsource/noto-sans` numa pasta de rascunho e copie os mesmos arquivos.
Os módulos WASM do pdf.js (JPEG 2000/JBIG2) não foram incluídos. PDFs com esses formatos de imagem podem não renderizar essas imagens.
