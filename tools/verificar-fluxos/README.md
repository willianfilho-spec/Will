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

Seletores aceitam qualquer sintaxe do Playwright (`#id`, `.classe`, `text=...`, `role=button[name="Salvar"]`).

Cada fluxo roda em contexto limpo (sem `localStorage` herdado). Erros de console e exceções de página fazem o fluxo falhar, porque um app que "funciona" com erro no console não cumpre o critério 1 da skill.
