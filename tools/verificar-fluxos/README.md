# Verificador de fluxos (Playwright)

Executa no navegador os fluxos descritos em um arquivo JSON, salva capturas de tela de cada passo marcado e gera um relatório. É a etapa de verificação do agente `replicador-software`.

## Uso

```bash
node tools/verificar-fluxos/verificar.mjs tools/verificar-fluxos/exemplos/guia-sigaa-editor.json
```

Saída: `tools/verificar-fluxos/saida/<nome>/` com `relatorio.md`, `relatorio.json` e as capturas `.png`. Código de saída 0 se todos os fluxos passarem, 1 caso contrário.

Requer Node 18+ e o pacote `playwright` disponível (no ambiente em nuvem do Claude Code já vem instalado). Localmente: `npm i -D playwright && npx playwright install chromium`.

## Formato do arquivo

```json
{
  "nome": "meu-app",
  "servirPasta": "meu-app",        // serve esta pasta em http://127.0.0.1:<porta>/ (opcional)
  "urlBase": "http://localhost:5173", // use no lugar de servirPasta se o app tiver servidor próprio
  "fluxos": [
    {
      "nome": "Criar item",
      "viewport": { "width": 390, "height": 844 },  // opcional
      "passos": [
        { "ir": "/" },
        { "clicar": "#bNew" },
        { "preencher": "#titulo", "valor": "Teste" },
        { "tecla": "Enter" },
        { "verVisivel": "text=Teste" },
        { "verTexto": "#lista", "contem": "Teste" },
        { "verQuantidade": "#lista li", "igual": 2 },
        { "recarregar": true },
        { "captura": "apos-recarregar" },
        { "esperar": 300 }
      ]
    }
  ]
}
```

### Passos para upload, download e interação com o mouse

```json
{ "enviarArquivo": "#arquivoPdf", "arquivo": "tools/verificar-fluxos/fixtures/documento-teste.pdf" },
{ "clicar": "#pagina-1 canvas", "posicao": [0.2, 0.5] },
{ "arrastar": "#pagina-1 .sobreposicao", "de": [0.1, 0.2], "ate": [0.6, 0.3] },
{ "verExpressao": "document.querySelectorAll('.anot').length === 2" },
{ "semRolagemHorizontal": true },
{ "baixar": "#bBaixarPdf", "validar": {
    "nomeContem": "-editado.pdf", "assinatura": "%PDF", "bytesMin": 1000,
    "textoContem": ["trecho"],
    "pdfPaginas": 3, "pdfTextoContem": ["frase"], "pdfTextoNaoContem": "outra" } }
```

- `enviarArquivo`: preenche um `<input type="file">` (setInputFiles). Caminhos relativos à pasta onde o comando é executado (a raiz do repositório).
- `posicao`, `de` e `ate`: **frações** (0 a 1) da largura e da altura do elemento. Antes de clicar ou arrastar, o verificador rola a página até o ponto inicial ficar no meio da tela, longe de cabeçalhos fixos.
- `verExpressao`: avalia JavaScript na página e espera até o resultado ser verdadeiro (até 5 s).
- `semRolagemHorizontal`: falha se a página for mais larga que a janela (útil no teste de celular).
- `baixar`: clica, espera o download, salva em `saida/<nome>/` e valida. `textoContem` lê o arquivo como UTF-8. `assinatura` confere os primeiros bytes (`%PDF`, `PNG`).
  `pdfPaginas`, `pdfTextoContem` e `pdfTextoNaoContem` abrem o PDF baixado com o pdf.js **servido pelo próprio app** (mesma origem), em outra aba do Chromium. Para isso, informe no topo do arquivo `"pdfjs"` e `"pdfjsWorker"` (caminhos relativos à `urlBase`/`servirPasta`). Assim não é preciso instalar nada no Node.
- `passar`: move o mouse (sem clicar) até a fração `posicao` do elemento (hover). `selecionar` + `valor`: escolhe uma opção de `<select>`.
- `baixar` → `validar` aceita também: `bytesMax`; `pdfCapturaPagina: n` (salva um PNG da página n do PDF baixado, renderizada pelo pdf.js, ao lado do arquivo); `pdfAmostras: [{ pagina, fx, fy, perto|longe: "#rrggbb", tolerancia }]` (cor do pixel na fração (fx, fy) da página renderizada: prova visual de que o fundo foi preservado). Downloads com o mesmo nome no mesmo fluxo recebem sufixo `-2`, `-3`.
- `semRedeExterna: true` (no fluxo): falha se qualquer requisição, inclusive de workers, sair para fora do servidor do app. Garante que nada vem de CDN.
- `tempo` (em qualquer passo): muda o limite de espera de 5000 ms.

Exemplo completo: `tools/verificar-fluxos/editor-pdf.json`, com o PDF de teste gerado por `node tools/verificar-fluxos/fixtures/gerar-pdf-teste.mjs`.

Seletores aceitam qualquer sintaxe do Playwright (`#id`, `.classe`, `text=...`, `role=button[name="Salvar"]`).

A pasta `saida/<nome>/` é esvaziada no início de cada execução, para que capturas de falhas antigas não se misturem às novas.

Cada fluxo roda em contexto limpo (sem `localStorage` herdado). Erros de console e exceções de página fazem o fluxo falhar, porque um app que "funciona" com erro no console não cumpre o critério 1 da skill.
