# Assistente de Conciliação Contábil (MVP)

Lê um extrato bancário em CSV ou XLSX, confere o saldo, classifica cada
movimento por regras, passa pela revisão de uma pessoa e só então gera o
arquivo de importação para o sistema contábil.

É uma ferramenta de apoio. Nada é exportado para importação sem aprovação
humana; a responsabilidade técnica continua sendo do contador.

> **Sobre o Fortes.** O arquivo de importação é montado a partir de
> `config/layout_importacao.json`. O layout que acompanha o projeto é
> provisório e **não foi validado no Fortes**. Para validar, é preciso um
> arquivo que o Fortes já tenha aceitado (ou o layout oficial de importação de
> lançamentos) para reproduzir as colunas.

## Como executar

Requer Python 3.10 ou superior. Para ler XLSX, instale `openpyxl`
(`pip install openpyxl`). CSV não exige nada.

```bash
cd conciliador-contabil
```

**1. Primeira rodada: classificar.**

```bash
python -m conciliador exemplos/extrato_exemplo.csv
```

Gera, na pasta `saida/`:

| Arquivo | Conteúdo |
|---|---|
| `lancamentos.csv` | todos os lançamentos, com status e regra aplicada |
| `revisao.csv` | o que precisa de decisão humana (`REVISAR` e `PENDENTE`) |
| `auditoria.jsonl` | uma linha por execução: quem, quando, com quais arquivos |

**2. Revisar.** Abra `saida/revisao.csv` no Excel. Em cada linha, ajuste
`conta_debito`, `conta_credito` e `historico` se for o caso, e troque o
`status` para `APROVADO`. Salve como CSV.

**3. Segunda rodada: aplicar a revisão.**

```bash
python -m conciliador exemplos/extrato_exemplo.csv --revisao saida/revisao.csv
```

Quando não resta nenhum `REVISAR` ou `PENDENTE`, o programa gera
`saida/importacao.csv`. Enquanto restar algum, esse arquivo não é gerado (e um
eventual arquivo de rodada anterior é apagado).

Opções:

| Opção | Para que serve | Padrão |
|---|---|---|
| `--revisao` | planilha de revisão preenchida | nenhuma |
| `--saldo-inicial`, `--saldo-final` | saldos, quando o arquivo não os traz | lidos do arquivo |
| `--regras` | regras e fornecedores | `config/regras.json` |
| `--plano` | plano de contas | `config/plano_de_contas.csv` |
| `--layout` | layout do arquivo de importação | `config/layout_importacao.json` |
| `--saida` | pasta de saída | `saida` |
| `--ia` | sugestão da IA para o que ficou sem regra | desligado |

Use uma pasta `--saida` por empresa, conta e mês (por exemplo
`--saida saida/empresa-x/2026-10`), para que as revisões não se misturem.

Testes:

```bash
python -m unittest discover -s tests
```

## Como funciona

```
extrato ─► leitor ─► conferência ─► regras ─► revisão ─► exportador
(CSV/XLSX)           de saldo     (+ IA opc.)  manual    ├─ lancamentos.csv
                                                         ├─ revisao.csv
                                                         ├─ importacao.csv (só sem pendências)
                                                         └─ auditoria.jsonl
```

1. **Leitura (`leitor.py`)**. Aceita CSV e XLSX (primeira aba). Procura a linha
   de cabeçalho nas 30 primeiras linhas, porque extratos costumam ter título
   antes da tabela. Reconhece data, descrição/histórico e valor, ou débito e
   crédito em colunas separadas, ou valor com coluna D/C. Linha ilegível
   interrompe o processamento e é apontada pelo número.

2. **Conferência de saldo (`pipeline.conferir_saldo`)**. Saldo inicial mais
   movimentos tem de dar o saldo final. Os saldos vêm das linhas "SALDO
   ANTERIOR/INICIAL" e "SALDO FINAL/ATUAL" do arquivo, ou dos parâmetros.
   Divergência interrompe tudo. Se os saldos não foram informados, o programa
   segue, mas avisa "NÃO CONFERIDO".

3. **Classificação (`regras.py`)**. Fornecedores cadastrados têm prioridade
   sobre as regras gerais. A comparação ignora maiúsculas, acentos e pontuação
   e casa palavra inteira. Sem regra, o movimento vai para a conta transitória.

4. **Revisão (`pipeline.aplicar_revisao`)**. Só linhas `APROVADO` são
   aplicadas. Uma aprovação é recusada se a conta não existir no plano, se
   ainda estiver na conta transitória, se a conta do banco tiver sido tirada do
   lado certo ou se o histórico estiver vazio. Data e valor nunca mudam: vêm do
   extrato.

5. **Exportação (`exportador.py`)**. O arquivo de importação segue o layout
   configurado. Cada execução concluída acrescenta um registro em
   `auditoria.jsonl`, com o hash dos arquivos de entrada, a regra aplicada a
   cada linha e o antes e depois de cada alteração manual.

### Status

| Status | Significado | Entra no arquivo de importação? |
|---|---|---|
| `CLASSIFICADO` | regra específica, sem ressalvas | sim |
| `APROVADO` | conferido por uma pessoa na revisão | sim |
| `REVISAR` | regra genérica, conflito entre regras, possível duplicidade ou sugestão da IA | bloqueia a geração |
| `PENDENTE` | sem regra; está na conta transitória | bloqueia a geração |

Linhas com mesma data, descrição e valor são marcadas como possível
duplicidade e vão para `REVISAR`. Elas **não são removidas**: dois PIX iguais
no mesmo dia podem ser legítimos, e apagar um deles faria o saldo não fechar.

## Como adaptar

**Plano de contas** (`config/plano_de_contas.csv`): colunas `codigo;descricao`.
O plano incluído é ilustrativo; substitua pelo plano usado no Fortes.

**Fornecedores e equivalências** (`config/regras.json`, seção `fornecedores`):

```json
{"nome": "NX / F. Olavo", "apelidos": ["NX", "F. OLAVO"], "conta": "2.1.1.01"}
```

Todos os apelidos levam ao mesmo fornecedor e à mesma conta. Opcionais:
`sentido` (padrão `saida`), `historico`, `revisar`.

**Regras gerais** (seção `regras`):

```json
{"nome": "Tarifas bancárias", "palavras_chave": ["TARIFA", "TAR"],
 "sentido": "saida", "conta": "4.1.2.01", "historico": "Tarifa bancária"}
```

- `sentido`: `entrada`, `saida` ou `ambos`.
- `revisar: true`: para regras que são suposição ("todo PIX recebido é de
  cliente"). O lançamento sai com conta sugerida, mas precisa de aprovação.
- A ordem importa: a primeira regra que casar é aplicada.

**Layout de importação** (`config/layout_importacao.json`): define delimitador,
codificação, cabeçalho, formato de data, separador decimal e a lista de
colunas. Cada coluna usa um `campo` do lançamento (`data`, `conta_debito`,
`conta_credito`, `valor`, `historico`, `documento`, `fornecedor`) ou um valor
`fixo` (código da empresa, centro de custo). Opcionais por coluna:
`tamanho_maximo` e `sem_pontuacao`. Depois que o Fortes aceitar um arquivo
gerado, troque `validado_no_sistema` para `true` para o aviso sumir.

## Sugestão por IA (opcional)

```bash
pip install anthropic
```

```bash
export ANTHROPIC_API_KEY="sua-chave"
```

```bash
python -m conciliador exemplos/extrato_exemplo.csv --ia
```

Só os movimentos sem regra são enviados, e apenas descrição e sentido (sem
valor nem data). A IA só pode responder com uma conta do plano ou
"indefinido", e toda sugestão sai como `REVISAR`. Ela não aprova nada, não
altera o plano de contas e não cria regras.

Antes de usar com dados reais, resolva a questão de privacidade: as descrições
trazem nomes de pessoas e empresas e saem do escritório para um serviço
externo (sigilo profissional e LGPD).

## O que ainda não existe

- **Layout do Fortes validado.** É o item que decide se a implantação funciona.
- **OFX e PDF.** OFX é o próximo formato natural; PDF depende do layout de cada
  banco e é o mais frágil.
- **Telas.** A revisão é feita na planilha `revisao.csv`. Não há interface web,
  login, perfis de usuário nem separação por empresa dentro do programa. O
  registro de auditoria grava o usuário do sistema operacional, o que não
  equivale a controle de acesso.
- **Conciliação com o controle interno.** O programa classifica o extrato. Ele
  não cruza com planilha de contas a pagar e a receber nem baixa títulos.
- **Vários bancos na mesma execução**, centro de custo por lançamento e
  desmembramento de um pagamento em principal, juros e multa.
- **Aprendizado de regras.** As aprovações manuais ficam registradas, mas ainda
  não viram sugestão de regra nova.

As regras de exemplo embutem escolhas contábeis que dependem do regime e da
política do escritório (pagamento a fornecedor debitando "Fornecedores a
Pagar", DAS debitando "Simples a Recolher", PIX recebido creditando "Clientes a
Receber"). Revise todas antes de usar.
