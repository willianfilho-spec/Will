# Mapa funcional — ferramenta "Editar PDF" (referência) → Folha Clara

Projeto: `editor-pdf/` · Modo **A** (recriar por link) · Alvo: **web** · Data: 2026-10-31

Referência indicada: `https://smallpdf.com/pt/editar-pdf#r=annotate`.

## 0. Acesso à referência (limitação importante)

- A página **não pôde ser aberta** nesta sessão. O WebFetch retornou `getaddrinfo ENOTFOUND smallpdf.com`.
  O Chromium via Playwright retornou `net::ERR_TUNNEL_CONNECTION_FAILED`. O domínio está fora da lista
  de rede permitida do ambiente. Nenhuma proteção foi contornada. Por isso **não há capturas** em `docs/editor-pdf/referencia/`.
- A única evidência obtida foi uma **busca na web** (títulos e resumos dos resultados, sem abrir as páginas).
  Os itens que vêm só dela estão marcados como `[OBSERVADO-indireto]`, ou seja, é fonte secundária, não a tela em si.
  Fontes que apareceram na busca: `smallpdf.com/pt/editar-pdf`, `smallpdf.com/pt/anotacoes-pdf`,
  `smallpdf.com/pt/blog/desenhar-em-pdf-online`, `smallpdf.com/pt/blog/como-digitar-em-pdf`, `smallpdf.com/pt/blog/mudar-cor-pdf`.
- Para transformar hipóteses em observações, libere `smallpdf.com` na configuração de rede da sessão e repita a análise.

## 1. Telas

| Tela | Objetivo / componentes | Evidência |
|---|---|---|
| Página de entrada da ferramenta | Área para escolher ou soltar o arquivo, texto de apresentação e perguntas frequentes | `[HIPÓTESE]`: padrão comum de ferramentas online de PDF; não visto |
| Editor | Visualização das páginas e barra de ferramentas com texto, desenho, destaque, formas, imagem e nota adesiva | `[OBSERVADO-indireto]` (busca: "texto, desenho, destaque ou nota adesiva"; "inserir imagens, formas") |
| Modo "annotate" (`#r=annotate`) | O fragmento da URL sugere que a ferramenta abre direto no modo de anotação | `[HIPÓTESE]`: inferido só pela URL |
| Tela de conclusão / download | Botão para baixar o resultado e, provavelmente, oferta de outras ferramentas | `[HIPÓTESE]` |
| Login / planos | Teste gratuito e plano pago | `[OBSERVADO-indireto]` (a busca cita "teste gratuito"); limites exatos `[INVESTIGAR]` |

## 2. Fluxos principais

1. **Anotar e baixar.** O usuário escolhe um PDF, as páginas aparecem, ele adiciona texto, destaque, desenho ou forma e baixa o PDF com as marcas. `[OBSERVADO-indireto]` para as ferramentas; a sequência exata de telas é `[HIPÓTESE]`.
2. **Editar texto existente.** A busca diz que é possível "editar o texto existente" e "clicar em texto, formas ou destaques existentes para ajustá-los". `[OBSERVADO-indireto]`. Como isso é feito (substituição real na camada de texto ou sobreposição) é `[INVESTIGAR]`.
3. **Inserir imagem.** `[OBSERVADO-indireto]`.
4. **Extrair conteúdo.** A referência, nesta ferramenta, **não** foi vista oferecendo extração de texto, páginas ou imagens. É uma **prioridade pedida pela usuária**, não uma funcionalidade observada. No mesmo fornecedor isso costuma estar em ferramentas separadas ("Dividir", "PDF para JPG", "PDF para Word"): `[HIPÓTESE]`.

## 3. Regras de negócio

- PDFs digitalizados são uma imagem grande e não permitem clicar em palavras: `[OBSERVADO-indireto]` (busca).
- Ferramentas de anotação gratuitas sem assinatura, com recursos completos possivelmente pagos: `[OBSERVADO-indireto]`, com informação contraditória nos resultados. Limites diários e tamanho máximo são `[INVESTIGAR]`.
- Arquivo enviado para o servidor do fornecedor e apagado depois de um tempo: `[HIPÓTESE]` (é o modelo usual de serviços online). Política real `[INVESTIGAR]`.

## 4. Dados

- Referência: arquivo PDF do usuário, provavelmente processado no servidor (`[HIPÓTESE]`), e conta/assinatura (`[INVESTIGAR]`).
- Folha Clara (decisão própria): o PDF original (bytes) e uma lista de anotações `{tipo, página, coordenadas em pontos, cor, espessura, texto, tamanho, imagem}` ficam no **IndexedDB do navegador** (sessão restaurada ao recarregar). Nada sai da máquina.

## 5. Integrações

- Referência: armazenamento em nuvem, login e pagamento: `[INVESTIGAR]`.
- Folha Clara: **nenhuma**. Não há servidor, login nem pagamento, portanto nada precisou ser `SIMULADO`.

## 6. Decisões de escopo da versão própria

| Item | Decisão |
|---|---|
| Nome e identidade | "Folha Clara", verde-petróleo `#135e57`, âmbar `#f4b942`, fundo papel `#f4f1ea`. Sem marca, logo nem textos da referência |
| Stack | HTML + CSS + JS puro (módulos ES), sem build. pdf.js 6.4.299 (Apache-2.0) para renderizar e extrair; pdf-lib 1.17.1 (MIT) para gravar. Ambos vendorizados em `editor-pdf/vendor/` |
| Anotações no PDF baixado | Desenhadas no conteúdo da página ("achatadas"), não como objetos de anotação editáveis |
| Editar texto existente | **Não implementado** como edição real. Oferecido como **"Cobrir e reescrever"**: retângulo branco por cima do trecho mais texto novo. O texto original continua no arquivo, por baixo do branco |
| Extrair texto | Camada de texto via pdf.js, por página e completa; copiar e baixar `.txt`. Sem OCR |
| Extrair páginas | Novo PDF com as páginas escolhidas (cópia real via pdf-lib), com ou sem as anotações |
| Extrair imagens | Duas funções separadas e rotuladas: (a) imagens **embutidas** decodificadas pelo pdf.js e salvas como PNG; (b) **página inteira renderizada** como PNG |
