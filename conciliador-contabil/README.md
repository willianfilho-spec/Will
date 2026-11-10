# Assistente de Conciliação Contábil (protótipo)

Lê um extrato bancário em CSV, classifica cada movimento com base em regras de
palavras-chave e gera um CSV de lançamentos em partidas dobradas, mais um
arquivo separado com tudo o que precisa de revisão humana.

É uma ferramenta de apoio. Os lançamentos precisam ser revisados antes de
qualquer importação; a responsabilidade técnica continua sendo do contador.

## Como executar

Requer apenas Python 3.10 ou superior. Não há dependências para o uso básico.

```bash
cd conciliador-contabil
```

```bash
python -m conciliador exemplos/extrato_exemplo.csv
```

Os arquivos saem na pasta `saida/`:

- `lancamentos.csv`: todos os lançamentos.
- `revisao.csv`: apenas os que têm status `REVISAR` ou `PENDENTE`.

Opções:

| Opção | Para que serve | Padrão |
|---|---|---|
| `--regras` | arquivo de regras | `config/regras.json` |
| `--plano` | plano de contas | `config/plano_de_contas.csv` |
| `--saida` | pasta de saída | `saida` |
| `--ia` | pede sugestão à IA para o que as regras não classificaram | desligado |

Testes:

```bash
python -m unittest discover -s tests
```

## Como funciona, passo a passo

```
extrato.csv ─► leitor.py ─► regras.py ─► pipeline.py ─► exportador.py ─► saida/*.csv
                              ▲   (ia.py, opcional)
              config/regras.json + config/plano_de_contas.csv
```

1. **Leitura (`conciliador/leitor.py`)**. Detecta a codificação (UTF-8 ou
   Latin-1) e o delimitador (`;`, `,`, tab ou `|`). Reconhece as colunas pelo
   nome: data, descrição/histórico e valor, ou então débito e crédito em
   colunas separadas, ou valor com coluna de tipo D/C. Converte valores no
   padrão brasileiro (`1.234,56`) e americano (`1,234.56`). Linhas cuja
   descrição começa com "SALDO" são ignoradas e contadas. Qualquer outra linha
   ilegível interrompe o processamento e lista todos os problemas com o número
   da linha.

2. **Regras (`conciliador/regras.py`)**. Carrega o plano de contas e as regras.
   Recusa-se a rodar se alguma regra apontar para conta inexistente. Uma regra
   casa quando alguma palavra-chave aparece como palavra inteira na descrição
   (sem diferenciar maiúsculas ou acentos) e o sentido confere (entrada, saída
   ou ambos).

3. **Montagem (`conciliador/pipeline.py`)**. Para cada movimento:
   - entrada: débito no banco, crédito na contrapartida;
   - saída: débito na contrapartida, crédito no banco.

   A contrapartida vem da primeira regra que casar. Quando nenhuma casa, o
   movimento vai para a conta transitória com status `PENDENTE`. Nenhum
   movimento é descartado. Ao final, o programa confere que o movimento líquido
   da conta banco nos lançamentos é igual à soma do extrato.

4. **Exportação (`conciliador/exportador.py`)**. Grava os CSVs com `;`, vírgula
   decimal e datas `dd/mm/aaaa`, em UTF-8 com BOM (abre direto no Excel em
   português).

### Os três status

| Status | Quando acontece | O que fazer |
|---|---|---|
| `CLASSIFICADO` | uma regra específica casou, sem ressalvas | conferência por amostragem |
| `REVISAR` | regra marcada como genérica, duas regras com contas diferentes casaram, possível duplicidade com regra genérica, ou sugestão vinda da IA | conferir um a um |
| `PENDENTE` | nenhuma regra casou; está na conta transitória | classificar manualmente e, se o caso se repetir, criar uma regra |

A coluna `observacao` diz o motivo. Movimentos com mesma data, descrição e
valor recebem o aviso "possível duplicidade", mas não são removidos, porque
dois PIX iguais no mesmo dia podem ser legítimos.

## Como adaptar ao escritório

**Plano de contas** (`config/plano_de_contas.csv`): duas colunas, `codigo;descricao`.
O plano que acompanha o protótipo é ilustrativo. Substitua pelo plano real.

**Regras** (`config/regras.json`):

```json
{
  "nome": "Energia elétrica",
  "palavras_chave": ["ENERGISA", "ENEL"],
  "sentido": "saida",
  "conta": "4.1.1.01",
  "historico": "Pgto energia elétrica",
  "revisar": false
}
```

- `sentido`: `entrada`, `saida` ou `ambos`.
- `revisar: true`: use em regras que são suposição (por exemplo, "todo PIX
  recebido é de cliente"). O lançamento sai com a conta sugerida, mas marcado
  para conferência.
- A ordem importa: a primeira regra que casar é aplicada. Coloque as
  específicas antes das genéricas.

`conta_banco` e `conta_transitoria`, no mesmo arquivo, definem a conta do banco
do extrato e a conta para o que não foi classificado.

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

Só os movimentos sem regra são enviados. A IA recebe a descrição e o sentido
(entrada ou saída), sem valor nem data, e só pode responder com uma conta que
exista no plano ou com "indefinido". Toda sugestão sai como `REVISAR`, com a
justificativa na coluna `observacao`. O uso da API é pago por consumo.

Antes de ligar essa opção com dados reais, decida a questão de privacidade: as
descrições de extrato costumam trazer nomes de pessoas e empresas, e esses
textos saem do escritório para um serviço externo. Isso envolve sigilo
profissional e LGPD e deve estar coberto no contrato com o cliente.

## Limitações conhecidas

- **Entrada**: apenas CSV. OFX, XLSX e PDF não são lidos. OFX seria o próximo
  formato natural, por ser estruturado; PDF é o mais frágil, porque cada banco
  tem um layout.
- **Saída**: CSV genérico. Não segue o layout de importação de nenhum sistema
  específico (Domínio, Alterdata, Totvs etc.). Para integrar de fato é preciso
  o layout oficial do sistema de destino, e só o `exportador.py` muda.
- **Um banco por execução**: a conta banco é única no arquivo de regras.
- **Um débito e um crédito por movimento**: não desmembra um pagamento em
  principal, juros e multa, nem separa retenções.
- **Não é conciliação completa**: o programa classifica o extrato. Ele não
  cruza com contas a pagar e a receber, não baixa títulos e não compara o saldo
  final com o razão.
- **As regras de exemplo embutem escolhas contábeis** que dependem do regime e
  da política do escritório. Exemplo: o pagamento do DAS é debitado em
  "Simples Nacional a Recolher", o que pressupõe provisão por competência; o
  recebimento por PIX é creditado em "Clientes a Receber", o que pressupõe
  receita já reconhecida na emissão da nota. Revise todas antes de usar.
- **Palavra-chave tem alcance limitado**: descrições vagas ("PIX ENVIADO JOAO
  DA SILVA") não têm como ser classificadas com segurança por regra, e ficam
  pendentes de propósito.
