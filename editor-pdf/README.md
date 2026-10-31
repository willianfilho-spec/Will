# Folha Clara — editar e extrair PDF no navegador

App web estática. Abre um PDF local, permite anotar e baixar o PDF com as marcas, e extrai texto, páginas e imagens. Todo o processamento acontece no navegador: nenhum arquivo é enviado para servidor.

## Executar

Precisa ser servida por HTTP (módulos ES e o worker do pdf.js não funcionam via `file://`):

```bash
npx http-server editor-pdf -p 8080   # ou: python3 -m http.server -d editor-pdf 8080
# abra http://localhost:8080
```

Testes: `node tools/verificar-fluxos/verificar.mjs tools/verificar-fluxos/editor-pdf.json`

## Funções

- **Editar**: texto, marca-texto, caneta, retângulo, elipse, linha, imagem (PNG/JPEG/WebP/GIF) e "Cobrir e reescrever". Para mover, use a ferramenta Mover; para apagar, o botão Apagar ou a tecla Delete. Desfazer com Ctrl+Z. Para editar um texto, dê duplo clique nele.
- **Baixar PDF**: as anotações são desenhadas no conteúdo da página ("achatadas"). Não viram objetos de anotação editáveis em outros leitores.
- **Extrair**: texto (por página e completo, copiar e baixar `.txt`), novo PDF com as páginas escolhidas (com ou sem anotações), imagens embutidas (decodificadas e salvas como PNG) e página inteira renderizada como PNG.
- **Sessão**: o último PDF e as anotações ficam no IndexedDB deste navegador e voltam depois de recarregar. "Fechar" apaga a sessão.

## Limitações conhecidas

- **Não edita o texto original** do PDF. "Cobrir e reescrever" põe um retângulo branco e texto novo por cima; o texto antigo continua no arquivo (aparece se alguém copiar o texto ou extraí-lo).
- O texto adicionado usa Helvetica (WinAnsi). Caracteres fora desse conjunto (emoji, alfabetos não latinos) viram `?` no PDF baixado.
- Sem OCR: PDFs digitalizados não têm texto para extrair.
- Não redimensiona anotações depois de criadas, não tem zoom e não abre PDFs com senha.
- Imagens JPEG 2000/JBIG2 dentro do PDF podem não aparecer (os módulos WASM do pdf.js não foram incluídos).

Bibliotecas: ver `vendor/LICENCAS.md`.
