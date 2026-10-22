# Editor PDF DIOAC 4B

Ferramenta (Tool) do Open WebUI para o modelo `Editor PDF DIOAC 4B`
(base: `qwen3:4b-instruct`). Localiza uma ocorrência exata de texto num PDF e
a substitui, preservando fonte incorporada, tamanho, cor e posição, com
backup automático e sem nunca sobrescrever o arquivo original.

## Revisão de bugs (2026-10-22)

Além dos dois problemas de fonte abaixo, uma auditoria do código encontrou e
corrigiu mais quatro bugs reais, todos reproduzidos com um PDF de teste antes
da correção:

1. **Fonte não incorporada quebrava com erro genérico.** Se o `/BaseFont` do
   PDF não tem arquivo embutido (comum em documentos simples gerados sem
   "incorporar fontes"), `doc.extract_font()` devolve um buffer vazio — e o
   código tentava montar uma fonte a partir dele, estourando uma exceção
   Python crua em vez de uma recusa clara. Agora: se for uma das 14 fontes
   padrão (Helvetica, Times, Courier etc.), a ferramenta usa a fonte
   embutida do próprio MuPDF diretamente, sem precisar de buffer. Se for
   outra família (ex.: "Arial", "Calibri" — os nomes mais comuns em PDFs
   reais do Windows, que o PyMuPDF **não** reconhece como alias de fonte
   padrão), a ferramenta agora recusa explicitamente, porque não existe
   arquivo de fonte para garantir a preservação exata do desenho das letras.
2. **Amostragem de cor de fundo frágil em espaçamento simples.** A versão
   anterior olhava um único ponto 3pt acima do texto para "adivinhar" a cor
   de fundo antes de apagar a área antiga. Em texto de espaçamento simples
   (o mais comum em documentos institucionais), esse ponto cai em cima da
   linha de cima com frequência, pintando um retângulo com a cor errada por
   cima do texto editado. Agora a ferramenta testa várias posições ao redor
   (acima, abaixo, esquerda, direita, com folgas diferentes) e só aceita uma
   amostra cujos pixels sejam uniformes o bastante para ser fundo de
   verdade; se nenhuma parecer confiável, cai para branco.
3. **`texto_original` vazio** não era rejeitado e tinha comportamento
   indefinido de busca. Agora retorna `STATUS=ERRO` imediato e claro.
4. **Número de página fora do intervalo do documento** (`pagina=99` num PDF
   de 3 páginas) derrubava a ferramenta com um `IndexError` cru em vez de
   uma recusa legível. Agora retorna `STATUS=RECUSADO` informando quantas
   páginas o documento realmente tem.

Nenhum desses quatro exigia um PDF "estranho" para acontecer — os quatro são
cenários realistas que um uso normal da ferramenta encontraria mais cedo ou
mais tarde.

## O que estava travando a versão anterior

O erro `fonte "/tt3" não suportada` tinha **duas causas**, não uma só. As
duas foram reproduzidas de forma controlada (PDF sintético com uma fonte
TrueType renomeada para "TT3", exatamente como fontes subsetadas pelo
Word/LibreOffice costumam aparecer) e a correção foi validada
empiricamente antes de ir para este arquivo. Vale entender as duas, porque a
segunda é silenciosa e é provavelmente o motivo de qualquer corrupção sem
mensagem de erro que a versão 4.1.0 ainda apresente.

**1) Nome de fonte usado diretamente (causa do erro explícito).**
`page.get_text("dict")` devolve o nome da fonte do trecho (ex.: `"TT3
Regular"`), mas esse nome não é um alias válido dentro do documento — é só
uma etiqueta informativa. Passar esse nome direto para `insert_text(...,
fontname=...)` falha, porque o PyMuPDF só reconhece as 14 fontes padrão ou
um alias que você mesmo registrou com `insert_font()`. A correção: extrair o
buffer real da fonte incorporada com `doc.extract_font(xref)` e registrá-lo
com `insert_font(fontname=alias, fontbuffer=buffer)` antes de inserir texto.

**2) Fonte incorporada sem tabela `cmap` (causa da corrupção silenciosa).**
Esta é a parte não óbvia. Quando o PyMuPDF faz o subsetting de uma fonte
Type0/Identity-H (o formato usado por Word, LibreOffice e a maioria dos
"imprimir como PDF"), ele **remove a tabela `cmap`** do buffer extraído,
porque fontes Identity-H não precisam dela para renderizar — a seleção de
glifo é feita por GID direto, não por Unicode. Isso quer dizer que
`fitz.Font(fontbuffer=...).has_glyph()` e `insert_text()` com uma string
Unicode normal **não funcionam de verdade** nesse buffer: na prática, os
caracteres novos são inseridos como caixas vazias (tofu), sem nenhum erro.
Isso foi reproduzido e fotografado antes da correção.

A correção: o PDF guarda, à parte da fonte, um CMap `/ToUnicode` (código →
Unicode) e, opcionalmente, um `/CIDToGIDMap` (código → GID; se ausente, é
`/Identity`, ou seja, GID = código). Juntando os dois dá exatamente o
mapeamento Unicode → GID que a fonte perdeu. A ferramenta faz o parse desses
dois objetos do PDF e reconstrói uma tabela `cmap` válida dentro do buffer
extraído (via `fontTools`) antes de registrá-lo com `insert_font`.

**3) Ainda existe um terceiro problema, mais sutil, e a ferramenta trata isso
recusando a edição em vez de arriscar.** Mesmo depois de reconstruído o
`cmap`, um caractere pode ter uma entrada válida de Unicode → GID e mesmo
assim **não ter contorno desenhado**, porque o subsetting só mantém o
desenho dos glifos que já apareciam em algum lugar do PDF original. Ou seja:
**só é seguro reaproveitar, no texto novo, caracteres que já existem em
algum lugar do próprio documento.** A ferramenta verifica isso letra por
letra (via `fontTools`, checando `numberOfContours`/componentes no `glyf`, ou
o charstring no `CFF `) e recusa a edição, nomeando exatamente qual
caractere falta, em vez de gerar um PDF com texto invisível.

Esses três pontos foram testados de ponta a ponta neste ambiente
(PyMuPDF 1.28.2, a mesma versão instalada no Open WebUI) com um PDF sintético
que reproduz a fonte "/TT3": os quatro cenários abaixo foram confirmados.

## O que a ferramenta garante (e o que recusa)

| Cenário | Resultado |
|---|---|
| Texto/ocorrência localizados, fonte cobre todos os caracteres novos, texto cabe no espaço original | `STATUS=SUCESSO`, PDF gravado em `EDITADOS`, `VALIDACAO=APROVADA` |
| Texto não encontrado (ou a ocorrência pedida não existe) | `STATUS=RECUSADO`, nada é alterado |
| Algum caractere do texto novo não existe (ou não tem contorno) na fonte incorporada | `STATUS=RECUSADO`, lista exatamente quais caracteres |
| Texto novo mais largo do que o espaço do texto original (com tolerância configurável) | `STATUS=RECUSADO` |
| Ocorrência atravessa dois trechos com tipografias diferentes | ignorada na contagem (nunca "adivinha" qual usar) |
| Fonte não incorporada e não é uma das 14 fontes padrão | `STATUS=RECUSADO` |
| `texto_original` vazio ou `pagina` fora do intervalo do documento | `STATUS=ERRO`/`RECUSADO` imediato, claro |
| Qualquer falha inesperada | `STATUS=ERRO`, backup preservado |

Em nenhum desses casos o arquivo original é alterado — a ferramenta
recalcula o hash SHA-256 do original antes e depois da operação e retorna
`STATUS=ERRO` se ele mudar por qualquer motivo. Imagens e elementos gráficos
dentro da área editada nunca são removidos pela redação (`apply_redactions`
roda com `images=PDF_REDACT_IMAGE_NONE` e `graphics=PDF_REDACT_LINE_ART_NONE`).

## Formato de retorno

Igual ao que já estava padronizado, para reduzir a chance de o modelo
reinterpretar o resultado:

```
STATUS=SUCESSO
ORIGINAL=...
BACKUP=...
EDITADO=...
PAGINA=...
OCORRENCIA=...
TEXTO_ORIGINAL=...
TEXTO_NOVO=...
FONTE_ORIGINAL=...
TAMANHO=...
VALIDACAO=APROVADA
```

Em caso de recusa/erro, as mesmas chaves aparecem (ecoando exatamente o que
foi recebido) mais `MOTIVO=` e `VALIDACAO=RECUSADA` ou `REPROVADA`.

## Instalação no Open WebUI

1. Workspace → Tools → **+** (novo tool) → cole o conteúdo de
   `manipulador_pdf_dioac.py`.
2. Salve. O Open WebUI lê o cabeçalho (`title`, `version`, `requirements`) e
   instala `pymupdf`, `fonttools` e `pydantic` no ambiente Python do
   contêiner/venv do Open WebUI automaticamente (se `requirements` não for
   respeitado na sua instalação, rode manualmente no Python usado pelo Open
   WebUI: `pip install pymupdf fonttools pydantic`).
3. Abra os **Valves** do tool e ajuste `BACKUP_DIR` e `OUTPUT_DIR` para os
   caminhos reais da sua máquina — por exemplo:
   - `BACKUP_DIR`: `C:\Users\<seu_usuario>\Desktop\DIOAC_PDF\BACKUP`
   - `OUTPUT_DIR`: `C:\Users\<seu_usuario>\Desktop\DIOAC_PDF\EDITADOS`

   (o valor padrão no código usa `~\Desktop\...`, mas como o Windows em
   português às vezes nomeia a pasta "Área de Trabalho" no explorador
   enquanto o caminho real do sistema continua `Desktop`, confirme o caminho
   exato abrindo as pastas já criadas e copiando o caminho da barra de
   endereços.)
4. Ative este tool apenas no modelo **Editor PDF DIOAC 4B** (ver
   `system-prompt.md` nesta pasta para a configuração completa do modelo).

## Testando

Depois de instalado, peça ao modelo algo como:

> Substitua "Portal Coord. Graduação" por "Portal Coord. Curso" no arquivo
> `Guia coordenador.pdf`.

O retorno deve ser o bloco `STATUS=SUCESSO` com os caminhos de `BACKUP` e
`EDITADO`. Abra o `EDITADO` e confira visualmente a página indicada em
`PAGINA=`.

## Limitações conhecidas

- Só é possível inserir, no texto novo, caracteres que já aparecem em
  algum lugar do PDF original (ver explicação acima). Isso é uma limitação
  de segurança deliberada, não um bug: não existe forma de "inventar" o
  desenho de um glifo que a fonte subsetada não contém.
- A cor de fundo da área apagada é estimada por amostragem de pixel em
  várias posições ao redor do texto, aceitando só amostras uniformes; para a
  grande maioria dos documentos institucionais (fundo branco) isso é
  irrelevante, mas em fundos texturizados/com gradiente a correspondência
  pode não ser perfeita.
- Fontes não incorporadas que não sejam uma das 14 fontes padrão (ex.:
  "Arial"/"Calibri" sem embedding, muito comuns em PDFs simples do Windows)
  são recusadas, não aproximadas — usar outra família mudaria o desenho das
  letras.
- A localização da ocorrência exige tipografia uniforme (mesma fonte,
  tamanho e cor) do começo ao fim do trecho buscado; se o texto atravessar
  uma mudança de formatação no meio, essa ocorrência é ignorada em vez de
  arriscar uma escolha errada.
