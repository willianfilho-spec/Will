# Bibliotecas de terceiros (vendorizadas)

Cópias sem alteração dos arquivos `dist`, obtidas do registro npm em 2026-10-31.

| Pasta | Pacote | Versão | Licença | Arquivos |
|---|---|---|---|---|
| `pdfjs/` | [pdfjs-dist](https://github.com/mozilla/pdf.js) (Mozilla) | 6.4.299 | Apache-2.0 (`pdfjs/LICENSE`) | `pdf.min.mjs`, `pdf.worker.min.mjs`, `standard_fonts/` (licenças Foxit e Liberation na própria pasta), `cmaps/` |
| `pdf-lib/` | [pdf-lib](https://github.com/Hopding/pdf-lib) | 1.17.1 | MIT (`pdf-lib/LICENSE.md`) | `pdf-lib.min.js` (UMD, expõe `window.PDFLib`) |

Para atualizar: `npm i pdfjs-dist pdf-lib` numa pasta de rascunho e copie os mesmos arquivos.
Os módulos WASM do pdf.js (JPEG 2000/JBIG2) não foram incluídos. PDFs com esses formatos de imagem podem não renderizar essas imagens.
