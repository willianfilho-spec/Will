# Arquivos-modelo para o Fortes

Esta pasta tem arquivos **fictícios** de uma empresa de exemplo
("EMPRESA EXEMPLO LTDA"). Nenhum dado de cliente está aqui. Os nomes de
clientes e fornecedores do plano de contas foram trocados por
`CLIENTE EXEMPLO nn LTDA` e `FORNECEDOR EXEMPLO nn LTDA`; as outras contas são as
do modelo de plano do Fortes.

## Para que servem

- **Testar o sistema sem usar dados de clientes**: importar o extrato, ver as
  regras funcionando, aprovar pendências e exportar.
- **Treinar a equipe**: o passo a passo da seção 5 percorre o fluxo inteiro em
  poucos minutos.
- **Conferir o leiaute**: o arquivo `modelo_importacao_fortes.csv` mostra, linha
  a linha, o que o sistema entrega para o Fortes (seção 3).

## O que tem em cada arquivo

Os três arquivos de movimento (OFX, CSV e planilha) trazem os mesmos
movimentos de outubro de 2026. A planilha só tem as saídas, como as planilhas
de despesas que os clientes enviam.

| Arquivo | O que é | Formato |
| --- | --- | --- |
| `plano_contas_fortes.csv` | Plano de contas no formato exportado pelo Fortes: classificação, descrição, código reduzido e outros campos, sem cabeçalho | Windows-1252 (cp1252), separador `;`, textos entre aspas, fim de linha CRLF |
| `regras_fortes.json` | Regras de classificação para esse plano: conta do banco e 7 regras (tarifa, IOF e juros, DAS, dois fornecedores, dois clientes) | JSON, ASCII, fim de linha LF |
| `extrato_exemplo.ofx` | Extrato bancário em OFX, com 13 movimentos e saldo final | ASCII, fim de linha CRLF |
| `extrato_exemplo.csv` | O mesmo extrato em CSV, com linhas de saldo anterior e saldo do dia | Windows-1252 (cp1252), separador `;`, vírgula decimal, fim de linha CRLF |
| `planilha_despesas_exemplo.xlsx` | Planilha de despesas (título DESPESAS, 11 saídas e linha de total) | Excel (.xlsx) |
| `modelo_importacao_fortes.csv` | Arquivo no leiaute de importação de lançamentos do Fortes, gerado pelo sistema a partir do OFX, depois da revisão | ASCII, separador `;`, fim de linha CRLF, sem cabeçalho |

## Leiaute de importação do Fortes

É o leiaute que `motor_contabil/exportador_fortes.py` gera. Cada linha é um
lançamento, com nove campos separados por ponto e vírgula:

```
data;debito;credito;valor;historico;;;;
```

| N. | Campo | Como é escrito |
| --- | --- | --- |
| 1 | Data | `dd/mm/aaaa`, por exemplo `05/10/2026` |
| 2 | Débito | Código **reduzido** da conta no plano (só números), não a classificação completa |
| 3 | Crédito | Código reduzido da conta, igual ao débito |
| 4 | Valor | Sempre positivo, com vírgula decimal, duas casas e **sem** separador de milhar: `1850,00`, `15000,00` |
| 5 | Histórico | Maiúsculas, só ASCII (sem acento), até 118 caracteres, terminado pela marca `[PREFIXO-AAAAMM-XXXXXXXX]` |
| 6 a 9 | Vazios | Quatro campos vazios no fim: a linha termina em `;;;;` |

Regras do arquivo todo:

- **Sem cabeçalho.** A primeira linha já é um lançamento.
- **Só ASCII.** Acentos saem sem acento, e um `;` dentro do histórico vira `,`.
- **Fim de linha CRLF** (padrão do Windows), inclusive na última linha.
- O sentido da operação está na ordem das contas, não no sinal do valor. Em
  uma entrada, o banco fica no débito; em uma saída, o banco fica no crédito.
- A marca no fim do histórico identifica o lançamento e impede duas linhas
  iguais no arquivo. Ela tem o prefixo da empresa (de 2 a 6 letras maiúsculas ou
  números, neste exemplo `EX`), o ano e o mês do lançamento (`AAAAMM`) e 8
  caracteres tirados da chave do lançamento no sistema. Os 118 caracteres do
  histórico incluem a marca; se o texto for longo, é o texto que é cortado, nunca
  a marca.
- O sistema recusa o lote inteiro, sem exportar nada, se uma conta não existir
  no plano, for sintética (sem código reduzido), se o valor for zero, se débito e
  crédito forem a mesma conta ou se houver duas linhas idênticas.

### Uma linha do modelo, campo por campo

```
05/10/2026;63;362;1850,00;PIX ENVIADO FUNCIONARIO EXEMPLO A [EX-202610-8875EFE9];;;;
```

| Campo | Valor | Significado |
| --- | --- | --- |
| Data | `05/10/2026` | Data do movimento no extrato |
| Débito | `63` | Código reduzido de "Salários a Pagar" (a conta foi escolhida na revisão) |
| Crédito | `362` | Código reduzido de "Banco Itaú", a conta do banco: é uma saída |
| Valor | `1850,00` | R$ 1.850,00, positivo, sem milhar |
| Histórico | `PIX ENVIADO FUNCIONARIO EXEMPLO A` | Texto do extrato, em maiúsculas |
| Marca | `[EX-202610-8875EFE9]` | Prefixo `EX`, mês `202610` (outubro de 2026) e 8 caracteres da chave |
| Campos 6 a 9 | `;;;;` | Quatro campos vazios |

Outras linhas do modelo que vale olhar:

- `01/10/2026;362;358;15000,00;TED RECEBIDA CLIENTE EXEMPLO 01 LTDA ...`: uma
  entrada. O banco (362) está no débito e o cliente (358) no crédito.
- `06/10/2026;333;362;169,00;TARIFA BANCARIA - TAR PLANO ADAPT 1 10/26 ...`: quando
  a regra tem histórico padrão, o texto fica "histórico padrão - texto do extrato".
- As duas linhas de `980,00` do dia 15/10 são operações legítimas iguais. No
  arquivo, só se distinguem pela marca, e é por isso que ela existe. No sistema,
  elas vão para revisão e precisam de aprovação (seção "Como usar", passo 4).

## Aviso importante

**O leiaute foi tirado de arquivos que o Fortes do escritório aceitou. Não há
manual oficial do Fortes nesta documentação.** O arquivo
`modelo_importacao_fortes.csv` em si **ainda não foi importado no Fortes**.

Para testar a importação:

1. Use uma **empresa de teste** do Fortes. **Nunca** importe este arquivo numa
   empresa real, porque os lançamentos usam as contas do plano de exemplo.
2. Importe com as opções que o escritório usa: **"Desconsiderar Identificador"**
   e **"Utilizar Código Reduzido"** marcadas (ver `INSTALACAO.md`).
3. Anote se alguma linha foi rejeitada e avise o responsável pelo sistema.

## Como usar: do cadastro à exportação

Os comandos são digitados no Prompt de Comando (ou terminal), dentro da pasta
`automacao-contabil`, com o ambiente do sistema ativado. Use uma pasta de dados
de teste **fora do projeto**, aqui `C:\teste_contabil\dados`, para não misturar
com os dados do escritório.

**1. Cadastrar a empresa de exemplo**

```bash
python -m motor_contabil.cli --dados C:\teste_contabil\dados cadastrar-empresa ex --nome "EMPRESA EXEMPLO LTDA" --cnpj 00.000.000/0001-91 --formato-plano fortes --conta 362 --prefixo EX --plano exemplos/fortes/plano_contas_fortes.csv --regras exemplos/fortes/regras_fortes.json
```

Resposta esperada: `empresa ex cadastrada em ...\dados\ex`. A conta `362` é
o código reduzido do banco no plano. O CNPJ `00.000.000/0001-91` é fictício. Se
a pasta `ex` já existir, o sistema responde "erro: já existe a pasta ex; escolha
outro identificador". Nesse caso, use outra pasta de dados.

**2. Importar o extrato OFX**

```bash
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex importar exemplos/fortes/extrato_exemplo.ofx
```

Resultado esperado:

```
Transações lidas: 13
  novas: 13
  já importadas antes (ignoradas): 0
Entradas no arquivo: R$ 23420,15
Saídas no arquivo:   R$ 15580,48
Liberado: 8
Pendente: 5
Bloqueado: 0
```

Importar o mesmo arquivo de novo não cria nada: aparece "novas: 0", "já
importadas antes (ignoradas): 13" e o aviso "arquivo idêntico já importado no
lote 1".

**3. Ver as pendências**

```bash
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex listar --status pendente
```

Aparecem 5 lançamentos:

- Três com o motivo "nenhuma regra reconhece o histórico": os dois pagamentos
  a funcionários (R$ 1.850,00 cada, dia 05/10/2026) e a retirada do sócio
  (R$ 3.000,00, dia 25/10/2026). Nenhuma regra do exemplo cobre esses casos de
  propósito, para treinar a revisão.
- Dois com o motivo "possível duplicidade: operação idêntica no mesmo
  arquivo": os dois PIX de R$ 980,00 ao FORNECEDOR EXEMPLO 02, dia 15/10/2026.
  Eles têm a mesma data, o mesmo valor, o mesmo histórico e o mesmo número de
  documento (101502), mas identificadores diferentes no banco. O sistema não
  decide sozinho se são duas operações ou uma repetida; quem decide é o
  revisor. Aqui são **duas operações legítimas** (dois pagamentos iguais), então
  as duas devem ser aprovadas. A conta (FORNECEDOR EXEMPLO 02) já vem sugerida
  pela regra.

A primeira coluna é o código do lançamento (12 caracteres).

**4. Aprovar as pendências escolhendo a conta**

Salários a pagar (código reduzido 63) para os dois funcionários, e
Empréstimos a Pagar (reduzido 375) para o sócio. Os dois PIX iguais já têm a
conta sugerida; basta aprovar sem informar conta. Cada comando usa o código do
lançamento mostrado por `listar` (os valores abaixo são os que o sistema gera
para este exemplo):

```bash
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex aprovar 8875efe9c510 --conta 2.01.01.03.01.0010-4
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex aprovar ac1d8bcfa64e --conta 2.01.01.03.01.0010-4
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex aprovar eb20232c8eb4 --conta 2.01.01.07.01.0001-6
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex aprovar e07e6addf5c8
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex aprovar 0d3e533742da
```

Cada um responde `liberado: ok`. Ao informar a conta, o comando `aprovar` pede a classificação
completa da conta (por exemplo `2.01.01.03.01.0010-4`), e não o código reduzido.

**5. Exportar**

```bash
python -m motor_contabil.cli --dados C:\teste_contabil\dados --empresa ex exportar lote.csv
```

Resposta esperada: `13 lançamentos exportados (lote 3)` (os lotes 1 e 2
foram as duas importações do OFX). Rodar `exportar` de novo responde `0 lançamentos exportados`:
exportar não repete lançamentos.

O arquivo `lote.csv` deve ficar **idêntico**, byte a byte, a
`modelo_importacao_fortes.csv`, inclusive nas marcas. As marcas dependem da
conta do banco e do identificador de cada movimento no extrato; por isso o
cadastro precisa usar `--conta 362` e `--prefixo EX`, como acima.

**6. Outros formatos (opcional)**

Os mesmos movimentos também podem ser importados do CSV e da planilha. Use uma
pasta de dados e uma empresa nova para cada teste, para não misturar os
resultados:

| Arquivo importado | Lidas | Entradas | Saídas | Liberados | Pendentes |
| --- | --- | --- | --- | --- | --- |
| `extrato_exemplo.ofx` | 13 | R$ 23420,15 | R$ 15580,48 | 8 | 5 |
| `extrato_exemplo.csv` | 13 | R$ 23420,15 | R$ 15580,48 | 8 | 5 |
| `planilha_despesas_exemplo.xlsx` | 11 | R$ 0,00 | R$ 15580,48 | 6 | 5 |

Nos três arquivos há 5 pendentes: os 3 sem regra (funcionários e sócio) e os 2
pagamentos iguais de `980,00` ao FORNECEDOR EXEMPLO 02, que vão para revisão
como "possível duplicidade: operação idêntica no mesmo arquivo". No OFX e no
CSV eles têm o mesmo documento (101502); a planilha não traz documento. Em
todos os casos são duas operações legítimas.

Importar o CSV e o OFX **na mesma empresa** não é recomendado: o sistema trata
o CSV como extrato novo, e os 13 movimentos ficam pendentes como possíveis
duplicidades. Se isso acontecer, é o comportamento esperado.

## Saldos para conferência

Os valores abaixo vêm do OFX e do CSV e foram conferidos somando os 13
movimentos:

| Item | Valor |
| --- | --- |
| Saldo anterior, em 30/09/2026 | R$ 10.000,00 |
| Entradas (15.000,00 + 8.420,15) | R$ 23.420,15 |
| Saídas | R$ 15.580,48 |
| Saldo final, em 31/10/2026 | R$ 17.839,67 |

Conta: 10.000,00 + 23.420,15 - 15.580,48 = 17.839,67. O saldo final é o que
consta no OFX (`LEDGERBAL`) e na última linha do CSV.

A planilha de despesas não permite essa conferência, porque só tem as saídas.
