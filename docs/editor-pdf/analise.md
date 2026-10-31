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
| Editar texto existente | Primeira versão: **"Cobrir e reescrever"** (retângulo branco + texto novo). Superada pela ferramenta **"Editar texto"**, ver seção 7 |
| Extrair texto | Camada de texto via pdf.js, por página e completa; copiar e baixar `.txt`. Sem OCR |
| Extrair páginas | Novo PDF com as páginas escolhidas (cópia real via pdf-lib), com ou sem as anotações |
| Extrair imagens | Duas funções separadas e rotuladas: (a) imagens **embutidas** decodificadas pelo pdf.js e salvas como PNG; (b) **página inteira renderizada** como PNG |

## 7. Editar o texto que já existe (pedido da usuária, 2026-10-31)

Fonte: relato da usuária sobre o uso real do app. `[OBSERVADO-relato]` = descrito por ela; o arquivo dela (`Design final.pdf`, cartaz de divulgação da UFMA exportado de ferramenta de design) **não foi fornecido ao agente**, então nada abaixo foi testado nele.

### 7.1 O que ela viu
- `[OBSERVADO-relato]` O PDF tem o texto como parte da imagem (sem camada de texto). Ela clicou em "DISCENTE!" com a ferramenta Texto.
- `[OBSERVADO-relato]` Quatro problemas: (1) não troca o texto existente; (2) o texto novo fica feio sobre o fundo (a cobertura era branca); (3) fonte, tamanho e cor ruins (Helvetica 16 pt vermelha, minúscula em página grande); (4) a caixa de digitação (fundo branco opaco) atrapalha.
- `[HIPÓTESE]` Em PDF só de imagem não existe "texto" para editar: o app precisa reconhecê-lo (OCR) e cobrir os pixels antigos. Por isso a edição é "cobrir com o fundo + desenhar texto novo", nunca uma troca de caracteres dentro do arquivo.

### 7.2 Mapa funcional da nova função

| Item | Decisão |
|---|---|
| Ferramenta "Editar texto" | Primeira da barra. Passar o mouse destaca as linhas detectadas; clicar abre o campo no lugar, preenchido; Enter/clicar fora confirma; Esc cancela; Shift+Enter quebra linha. Arrastar um retângulo marca à mão um texto não detectado |
| Linhas, PDF com camada de texto | pdf.js `getTextContent`, itens agrupados por linha de base e lacuna horizontal; usa o viewport do pdf.js (respeita /Rotate e CropBox). Nome da fonte (`fontExtraProperties`) define negrito/itálico e a família equivalente (Helvetica/Times/Courier ou Noto Sans) |
| Linhas, página sem texto | OCR tesseract.js no navegador, sob demanda, por página, com barra de progresso. Linhas com confiança < 50 ou pouco texto são descartadas (em fundo de foto o OCR inventa lixo) |
| Cobertura | Fundo amostrado do canvas renderizado, só do **anel externo** (3 px) da caixa. Cor única se uniforme; degradê vertical por faixas; colunas de degradê quando varia na horizontal. A caixa é estendida por pixels de tinta contíguos (acentos, cedilha) |
| Texto novo | Cor = média dos ~4% de pixels mais contrastantes com o fundo; tamanho = altura da linha (PDF: tamanho da fonte; OCR: altura de maiúscula ÷ 0,72); negrito pela fonte do PDF ou, no OCR, pela espessura do traço ÷ tamanho > 0,115 |
| Anotação | Tipo `edicao` (cobertura + texto). Mover leva só o texto; a cobertura fica sobre o texto antigo. Apagar, desfazer e persistência como as demais |
| Remoção real | Cobrir não apaga o texto do arquivo. Opção ao baixar: "Remover de vez o texto antigo (as páginas editadas viram imagem)": rasteriza só as páginas com `edicao`/`cobrir` (JPEG, escala até 3x) e as substitui |
| Texto novo (ferramenta Texto) | Fonte (Noto Sans embutida, Helvetica, Times, Courier), negrito, itálico, tamanho padrão ∝ largura da página, alinhamento, atalhos de cor UFMA, preto por padrão |

### 7.3 Limites conhecidos (`[HIPÓTESE]` até testar no arquivo real)
- A fonte decorativa do cartaz **não será reproduzida**: o texto novo sai em Noto Sans (ou Helvetica/Times/Courier). O app não identifica fonte a partir de pixels.
- O OCR erra acentos (ex.: "ATENÇÃO" virou "ATENCAO" no teste) e falha com fontes decorativas/itálicas sobre foto ou ruído.
- Fundo de foto/textura: a cobertura é um degradê amostrado nas bordas, sem grão nem detalhes; em imagens complexas fica um retalho visível.
- Não há zoom, rotação de texto inclinado (linhas a mais de 4° são ignoradas) nem redimensionamento por alças.
