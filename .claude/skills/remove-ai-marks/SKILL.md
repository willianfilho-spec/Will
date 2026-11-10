---
name: remove-ai-marks
description: Limpa Unicode invisível de textos (largura zero, controles bidirecionais, caracteres tag, espaços exóticos) e mede padronização de estilo com um pontuador estatístico, usando scripts Python embutidos na própria skill. Use quando o pedido for "remover marcas de IA", "remove marks ia", "limpar Unicode invisível", "tirar caracteres ocultos", "pontuar o texto", "medir se o texto está padronizado" ou /remove-ai-marks.
---

# Remove AI marks (versão local, com scripts embutidos)

Esta skill traz o código que executa. Os scripts ficam em `scripts/`, ao lado deste arquivo
(no repositório: `.claude/skills/remove-ai-marks/scripts/`). Só precisam de Python 3.9+ e da
biblioteca padrão: nada de Docker, venv ou `pip install`.

```bash
S=.claude/skills/remove-ai-marks/scripts
```

Se o diretório de trabalho não for a raiz do repositório, aponte `S` para a pasta `scripts/`
que acompanha este SKILL.md.

## O que faz e o que não faz

| Faz | Não faz |
| --- | --- |
| Inspeciona e remove Unicode invisível em texto UTF-8 (`.txt`, `.md`, `.html`, `.tex`, código) | Metadados e C2PA de imagem, PDF, DOCX, ODT |
| Pontua padronização de estilo (heurística) e compara antes/depois | Detectar IA ou provar autoria |
| Expõe as duas coisas por HTTP local, se for preciso | Reescrita automática (Camada B), marcas em pixel, áudio ou vídeo |

Se o pedido cair na coluna da direita, diga isso com clareza. Para documentos Word/PDF, a
skill `remover-marcas-de-ia` cobre a revisão; para reescrever prosa, `rewrite-human`.

## Fluxo

### 1. Inspecionar antes de mexer

```bash
python3 "$S/limpar_unicode.py" inspecionar ARQUIVO
```

Lista cada caractere encontrado, com código, nome, categoria e posição (linha:coluna).
Código de saída `1` quando há algo a tratar, `0` quando o texto está limpo. Para texto colado
na conversa, grave num arquivo temporário `.txt` ou use `-` para ler da entrada padrão.

### 2. Limpar

```bash
python3 "$S/limpar_unicode.py" limpar ARQUIVO
```

Grava `NOME.cleaned.EXT` e mantém o original. Use `--no-lugar` só se a pessoa pedir para
sobrescrever, ou `-o SAIDA` para escolher o destino.

Opções, todas desligadas por padrão porque alteram texto legítimo:

- `--nbsp`: converte o espaço não separável (U+00A0) em espaço comum. Cuidado: ele é
  tipografia correta em "R$ 10", "art. 5º" e antes de unidades.
- `--nfkc`: normalização NFKC. Desfaz ligaduras e letras de largura total, mas também
  transforma `²` em `2` e `™` em `TM`.
- `--homoglifos`: troca letras cirílicas/gregas idênticas a latinas, só em palavras que
  misturam alfabetos.

Ficam preservados: acentos, aspas curvas, travessões, emojis compostos (ZWJ), bandeiras
com tags e ZWJ/ZWNJ entre letras árabes ou índicas.

### 3. Pontuar o estilo

```bash
python3 "$S/pontuador_estatistico.py" ARQUIVO
python3 "$S/pontuador_estatistico.py" ANTES --comparar DEPOIS
```

Devolve um índice de padronização de 0 a 100 e os sinais que o compõem: uniformidade do
tamanho das frases e dos parágrafos, fórmulas de transição, travessões, tríades, contrastes
"não apenas X, mas Y" e variedade de vocabulário. Lista as fórmulas encontradas.

Ao relatar o número, diga sempre:

- é heurística com limiares escolhidos à mão, **não calibrada** em corpus rotulado;
- **não detecta IA** e não prova autoria; texto jurídico ou institucional escrito por gente
  costuma pontuar alto;
- vale para comparar versões do mesmo texto, não para classificar um texto isolado;
- abaixo de 150 palavras o resultado vem marcado como não confiável.

### 4. Relatório

Informe o que foi removido (contagem por categoria, tirada do relatório), onde ficou o arquivo
limpo, o índice antes/depois se foi medido, e o que ficou fora do alcance da skill. Limpar
Unicode não altera a redação: se o texto precisa soar diferente, isso é trabalho de revisão.

## Serviço HTTP (opcional)

Para quem prefere chamar por `curl` ou integrar com outra ferramenta. Usa os mesmos scripts.

```bash
bash "$S/iniciar_servico.sh"
```

Sobe em `http://127.0.0.1:8765` (porta em `WATERMARKS_SERVICE_PORT`) e confirma o `/health`.
Só escuta na própria máquina. Se `WATERMARKS_SERVER_API_KEY` estiver definida, todas as rotas
exigem `Authorization: Bearer <chave>`.

| Método | Rota | Corpo | Resposta |
| --- | --- | --- | --- |
| GET | `/health` | — | `{"ok": true, "version": ...}` |
| GET | `/capabilities` | — | o que existe e o que não existe neste serviço |
| POST | `/inspect` | `{"file": "<base64>", "name": "notas.md"}` | `{"ok", "kind", "suspicious", "report"}` |
| POST | `/clean` | idem + `"options"` | `{"ok", "kind", "cleaned": "<base64>", "report"}` |
| POST | `/detect` | `{"file": "<base64>", "name": "notas.txt"}` | `{"ok", "kind", "detections": [...]}` |

`options` de `/clean`: `nfkc`, `aggressive_homoglyphs`, `nbsp`, `detect_before`, `detect_after`.
Arquivo que não é texto devolve 400; `strategy` (reescrita) também.

```bash
WM="http://127.0.0.1:${WATERMARKS_SERVICE_PORT:-8765}"
curl -s -X POST "$WM/clean" -H 'Content-Type: application/json' \
  -d "{\"file\": \"$(base64 < notas.md | tr -d '\n')\", \"name\": \"notas.md\"}"
```

Decodifique o campo `cleaned` (base64) para gravar o resultado.

## Testes

```bash
python3 "$S/testes.py"
```

## Uso pretendido

Higiene do próprio conteúdo: caracteres ocultos quebram busca, comparação de versões,
contagem de caracteres e colagem em sistemas. Não apresente o resultado como prova de que
um texto foi escrito por uma pessoa, e não use para ocultar o uso de IA onde a declaração
é exigida (trabalho acadêmico, edital, periódico).
