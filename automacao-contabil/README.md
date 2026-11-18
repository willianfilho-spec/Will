# Automação de lançamentos contábeis a partir de extratos

Prova de conceito do projeto de Daiane, Luciana e Willian (proposta revisada
após a reunião de 9/11/2026). Transforma extratos bancários em lançamentos
contábeis revisados e prontos para importação, sem gerar duplicidades.

> **Estado atual:** protótipo testado apenas com dados fictícios. O leiaute de
> exportação é provisório e não corresponde a nenhum sistema contábil
> específico. Não usar com dados de clientes antes do piloto descrito abaixo.

## O que faz e o que não faz

| Faz | Não faz (ainda) |
| --- | --- |
| Lê OFX (1.x e 2.x), CSV, planilhas Excel (.xlsx) e o extrato Itaú em PDF | Ler PDF de outros bancos |
| Impede lançamento duplicado ao reprocessar ou sobrepor extratos | Ler o razão emitido pelo Fortes (a conferência usa os arquivos importados) |
| Classifica por regras aprovadas pelo contador | Decidir sozinho casos ambíguos |
| Sugere contas por IA, sempre como pendência | Liberar lançamento sugerido pela IA sem aprovação |
| Bloqueia contas inexistentes, sintéticas e valores zero | Validar documentação comprobatória (ITG 2000) |
| Registra quem aprovou, descartou ou exportou cada lançamento | Gerar arquivo no leiaute do Domínio, Alterdata etc. |

A distinção da proposta continua valendo: **gerar lançamentos a partir do
extrato não é conciliar**. A conciliação exige confrontar o extrato com os
registros contábeis existentes; isso fica para uma etapa posterior.

## Como o fluxo funciona

```
extrato (OFX/CSV)
   │  leitores/      lê e padroniza (valores em Decimal, nunca float)
   ▼
chave de idempotência   já existe? → ignora (não cria nada)
   │  idempotencia.py
   ▼
regras do contador      uma regra casa → classifica
   │  regras.py         duas regras divergem → pendente (não escolhe)
   ▼
IA (opcional)           só para o que nenhuma regra reconheceu → pendente
   │  classificador_ia.py
   ▼
validação               conta inexistente/sintética, valor zero → bloqueado
   │  motor.py          possível duplicidade, sugestão da IA → pendente
   ▼                    tudo certo → liberado
revisão humana          aprovar / corrigir conta / descartar com motivo
   ▼
exportação              só liberados; exportar de novo não repete nada
```

### Duplicidade: as três situações tratadas

1. **Mesmo arquivo processado duas vezes**: nada é criado na segunda vez. A
   chave da transação é a chave primária no banco de dados, então a proteção
   não depende apenas do código.
2. **Duas operações legítimas iguais** (mesma data, valor e histórico): as duas
   são preservadas e vão para revisão como "possível duplicidade". Quem decide é
   o revisor. Se o número do documento for diferente, não há alerta.
3. **Banco que muda o FITID a cada download**: a chave principal não reconhece
   a repetição, mas uma segunda chave, baseada no conteúdo, segura o
   lançamento como pendente.

Limitação conhecida: em extratos sem FITID, se o banco mudar o texto do
histórico entre dois downloads, a repetição não é reconhecida. Isso precisa ser
testado com extratos reais de cada banco usado pelos clientes.

## Instalação e uso

Requer Python 3.10 ou superior. O núcleo usa só a biblioteca padrão.

```bash
cd automacao-contabil
python -m venv .venv && . .venv/bin/activate   # no Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Interface de conferência (abre no navegador, roda localmente):

```bash
streamlit run app.py
```

Cuidados já configurados em `.streamlit/config.toml` (valem quando o app é
iniciado de dentro da pasta `automacao-contabil`):

- o Streamlit não envia estatísticas de uso (por padrão ele envia);
- o app só aceita conexões do próprio computador;
- o botão "Deploy" (publicar na nuvem do Streamlit) fica oculto.

Cada exportação fica guardada como lote. O arquivo de qualquer lote pode ser
baixado de novo na seção 3, idêntico ao original, sem que os lançamentos
voltem a ficar disponíveis para nova exportação. Downloads ficam registrados na
trilha de auditoria (o evento registra o clique, não confirma que o navegador salvou o arquivo).

O campo "Responsável pela revisão" é só uma identificação declarada, não um
login. Controle de acesso de verdade é requisito da versão para vários
escritórios.

Linha de comando:

```bash
python -m motor_contabil.cli importar exemplos/extrato_exemplo.ofx
python -m motor_contabil.cli listar --status pendente
python -m motor_contabil.cli aprovar 20dc839db8da --conta 2.1.1.01.001
python -m motor_contabil.cli descartar f4d215cc0bd0 --motivo "duplicado pelo banco"
python -m motor_contabil.cli exportar lancamentos.csv
```

Testes:

```bash
pytest
```

## Importar extrato na interface

É a seção "1. Importar extrato" do aplicativo. Passos: escolha o arquivo,
clique em "Processar extrato" e leia o resultado.

**Formatos aceitos:** `.ofx` e `.ofc` (o melhor, baixado no internet banking),
`.csv` e `.txt` com cabeçalho (colunas data, histórico e valor), `.xlsx` com
uma única planilha e `.pdf` do Itaú no modelo Entradas e Saídas. O tamanho
máximo é 20 MB por arquivo.

**O arquivo é testado antes de ser guardado.** O sistema lê o arquivo numa
cópia temporária. Só se a leitura der certo ele guarda o original em
`dados/<empresa>/arquivos` e cria o lote. Arquivo recusado não é guardado e
não cria lote.

**Quando a importação dá certo, o resultado mostra:**

- o título "Extrato importado" e uma frase com o total de transações lidas, as
  novas e as já importadas antes;
- os números: Lidas, Novas, Já importadas, Liberados, Pendentes e Bloqueados;
- Entradas no arquivo e Saídas no arquivo, em reais (as saídas aparecem com
  sinal de menos, por exemplo `-R$ 3.245,00`);
- o período: de que dia a que dia vão as transações do arquivo;
- avisos ("Atenção: ..."), por exemplo lançamentos pendentes ou bloqueados que
  pedem revisão na seção 2, ou arquivo idêntico já importado antes;
- "O que fazer", quando há uma próxima ação.

**Reimportar o mesmo arquivo** não cria nada. O título passa a ser "Nada de
novo neste extrato", com Novas igual a zero, e o aviso "Nenhuma transação
nova: todas as linhas deste arquivo já estavam no sistema."

**Quando o arquivo é recusado**, a tela mostra "Arquivo não importado", o que
aconteceu e "O que fazer". Os textos abaixo são os que o sistema gera
(`a.csv`, `a.xlsx` etc. são o nome do arquivo enviado).

| Mensagem | O que fazer |
| --- | --- |
| "O arquivo a.doc é do tipo .doc, que o sistema não lê." | Envie em .ofx, .ofc, .csv, .txt, .xlsx ou .pdf. O ideal é o OFX do internet banking. |
| "O arquivo a.csv está vazio (0 bytes)." | Baixe o extrato de novo no internet banking e confira se o arquivo abre antes de enviar. |
| "O arquivo a.csv tem 21,0 MB e o limite é 20 MB." | Baixe o extrato por períodos menores (um mês por vez) e envie um de cada vez. |
| "a.csv: arquivo sem cabeçalho" ou "a.csv: não encontrei coluna de valor" | Exporte o extrato de novo em CSV com cabeçalho, com as colunas data, histórico e valor. |
| "a.csv, linha 3: sem valor", "a.csv, linha 3: data inválida: '32/13/2026'" ou "a.csv, linha 3: valor monetário inválido: 'abc'" | Corrija a linha citada no arquivo e envie de novo, ou baixe o extrato novamente no banco. |
| "O arquivo a.csv foi lido, mas não tem nenhuma transação." | Baixe o extrato de novo, escolhendo um período com movimentação, e confira o cabeçalho (data, histórico e valor). |
| "a.ofx: transação 2 sem valor ou data" ou "O arquivo a.ofx está corrompido ou incompleto." | Baixe o OFX de novo no internet banking e envie o arquivo novo. |
| "O arquivo a.xlsx não é uma planilha .xlsx válida." | Exporte a planilha de novo em formato .xlsx (Excel) ou use o OFX do banco. |
| "a.xlsx: tem 2 planilhas. Envie um arquivo com uma única planilha de movimentação, para não misturar meses ou contas." | Envie um .xlsx com uma única planilha de movimentação (cabeçalho com data e valor), ou use o OFX do banco. |
| "a.pdf: não reconheci o extrato Itaú (Entradas e Saídas)" ou "a.pdf: a soma dos movimentos não confere com o saldo impresso. Nada foi importado." | Só é aceito o extrato do Itaú no modelo Entradas e Saídas. Baixe o PDF de novo no internet banking, sem editar, e envie. |
| "Não foi possível ler os caracteres do arquivo a.csv (codificação desconhecida)." | Salve o arquivo como UTF-8 ou exporte o extrato de novo no banco. |

Para qualquer outro erro, o "O que fazer" é: "Confira se o arquivo é o extrato
da empresa e envie de novo; se persistir, guarde o arquivo e avise o
responsável pelo sistema."

Na linha de comando (`motor_contabil.cli importar`), esta tela não é usada.

## Parametrização por empresa

- `exemplos/plano_contas.csv`: `codigo;descricao;tipo;codigo_exportacao`.
  `tipo` é A (analítica) ou S (sintética). `codigo_exportacao` é o código que
  o sistema de destino espera (por exemplo, o código reduzido); se vazio,
  usa o próprio código.
- `exemplos/regras.json`: a conta do banco e as regras (`padrao` é expressão
  regular sobre o histórico sem acentos, em maiúsculas).

Todos os arquivos de exemplo são fictícios.

## IA: como está configurada

Desligada por padrão. Quando ligada (`--ia` na CLI ou a caixa na interface):

- recebe só o histórico, com CPF/CNPJ mascarados, e o sentido (entrada/saída).
  Valor, data e conta bancária não são enviados;
- só pode responder contas analíticas do plano (restrição no esquema da
  resposta) e a resposta é validada de novo pelo motor;
- recusa, erro ou resposta fora do plano viram pendência, nunca lançamento;
- modelo configurável pela variável `MOTOR_CONTABIL_MODELO`;
- requer o pacote `anthropic` e uma credencial configurada (`ANTHROPIC_API_KEY`).

**Ponto de atenção (LGPD):** históricos de PIX trazem nomes de pessoas. O
mascaramento não remove nomes. Antes de ligar a IA com dados reais, é preciso
decidir se esse envio é aceitável, sob qual base legal e com qual contrato de
tratamento de dados com o fornecedor.

## O que falta para a especificação definitiva

Perguntas para Daiane e Luciana (sem elas, as próximas etapas ficam em
suposição):

1. **Qual sistema contábil recebe os lançamentos?** E qual o leiaute de
   importação usado hoje (um arquivo de exemplo aceito pelo sistema resolve)?
2. **A Skill atual**: entradas, saídas, regras que ela já aplica e erros
   conhecidos. As regras dela devem virar o `regras.json` inicial.
3. **Plano de contas real** de uma ou duas empresas piloto.
4. **Extratos reais** (com autorização dos clientes) de pelo menos dois bancos
   diferentes, mais os lançamentos que vocês fizeram manualmente a partir
   deles. É esse par que permite medir acerto de classificação e duplicidade.
5. O histórico do lançamento deve seguir algum padrão do escritório?

## Próximos passos sugeridos

1. Exportador no leiaute do sistema escolhido, testado com importação real.
2. Teste de reprodução: rodar o motor sobre extratos já escriturados e
   comparar lançamento a lançamento com o que foi feito manualmente.
3. Leitura de Excel e de outros formatos que aparecerem nos arquivos reais.
4. Regras aprendidas na revisão: quando o revisor corrige a mesma conta várias
   vezes, sugerir uma nova regra para o contador aprovar.

## Integridade dos lotes

Novas exportações preservam os bytes originais no SQLite. Alterações futuras no
plano ou no exportador não mudam o download desses lotes. Lotes de versões antigas
sem cópia preservada exigem recuperar o CSV original no backup do escritório;
o aplicativo não recria um arquivo que poderia ser diferente e não libera esses
lançamentos novamente. Faça backup do banco e dos arquivos originais.

Exportação, aprovação e descarte usam transação com bloqueio de escrita antes
da consulta, evitando decisões sobre estados desatualizados em acessos simultâneos.
Valores não finitos e frações de centavo são recusados, sem arredondamento silencioso.

## Exportação para o Fortes

`motor_contabil/exportador_fortes.py` gera o arquivo no leiaute de importação
de lançamentos que o Fortes Contábil já aceitou no escritório:
`data;debito;credito;valor;historico;;;;`, sem cabeçalho, em ASCII, com fim de
linha CRLF, contas pelo código reduzido e histórico de até 118 caracteres
terminado por uma marca que identifica o lançamento.

```python
from motor_contabil import ExportadorFortes, PlanoDeContas
plano = PlanoDeContas.carregar_fortes("plano_exportado_do_fortes.csv")
motor.exportar("lote.csv", ExportadorFortes(plano, prefixo_marca="NX"))
```

Se uma conta do lote não existir no plano, for sintética ou estiver sem código
reduzido, o lote inteiro é recusado com a lista dos problemas, e nenhum
lançamento é marcado como exportado. O leiaute foi conferido contra arquivos
reais, mas a aceitação pelo Fortes de um lote gerado por este exportador ainda
precisa ser testada com uma importação real.

## Planilhas Excel (.xlsx)

`motor_contabil/leitores/xlsx_extrato.py` lê as planilhas mensais de
movimentação que os clientes enviam (título, cabeçalho DATA / LANÇAMENTO
BANCÁRIO / DESCRIÇÃO / VALOR / CAIXA/BANCO e linha de total). Usa só a
biblioteca padrão e lê o valor como o texto gravado no arquivo. Regras:

- título DESPESAS acima do cabeçalho: todos os valores são saídas; RECEITAS:
  entradas; sem título, vale o sinal;
- o histórico junta o texto das colunas que não são data, valor ou caixa/banco;
- linha só com números e sem data (total) é ignorada; linha com texto e sem
  data é erro; movimento sem nenhum texto entra como "SEM HISTORICO NA
  PLANILHA" e vai para revisão;
- arquivo com mais de uma planilha, CAIXA/BANCO preenchida, valor negativo em
  planilha de despesas ou fração de centavo são recusados com a linha.

Uma planilha de despesas traz só as saídas. Ela serve para gerar lançamentos,
mas não permite conferir o saldo do banco, que depende do extrato completo.

## Regras sugeridas a partir do histórico

`python -m motor_contabil.sugerir_regras` junta cada movimento com o
lançamento que o escritório já importou no Fortes (mesma data, mesmo valor,
banco na partida certa) e sugere uma regra só para o histórico que aparece ao
menos duas vezes e foi lançado sempre na mesma conta. Contas passadas em
`--nunca` (sócios, empréstimos, folha, guias de tributos) nunca viram regra.
O arquivo gerado é uma sugestão para o contador revisar e contém nomes de
favorecidos: guarde-o com os dados do cliente, fora do repositório.

## Conferência do banco (conciliação)

`motor_contabil/conciliacao.py` confronta o extrato completo com os
lançamentos que movimentam a conta do banco nos arquivos já importados no
Fortes: saldo em cada fim de mês e pareamento movimento a movimento (mesma
data, mesmo valor, banco na partida certa). Saldo igual com sobras dos dois
lados é tratado como não conciliado, porque são erros que se compensam.

```bash
python -m motor_contabil.conciliacao --extrato extrato_itau.pdf \
    --importados lancamentos_importados.csv --banco 362
```

O extrato Itaú em PDF (`leitores/itau_pdf.py`, requer `pdfplumber`) é
recusado inteiro se a soma dos movimentos de algum dia não der o saldo
impresso pelo banco. Na interface, a conferência fica na seção 4.

Limite atual: a contabilidade é representada pelos arquivos importados, não
pelo razão emitido pelo Fortes. Lançamento apagado ou alterado à mão no Fortes
não aparece aqui; para isso, compare também o saldo da conta no balancete.

## Backup e restauração

`motor_contabil/backup.py` copia a pasta de dados (bancos SQLite e arquivos)
para outro dispositivo. Cada cópia é uma pasta `backup_AAAAMMDD_HHMMSS` com
um manifesto de hashes; os bancos são copiados pela API de backup do SQLite,
consistentes mesmo com o aplicativo aberto. Ficam a última cópia de cada um
dos 30 dias mais recentes e a última de cada um dos 12 meses mais recentes.

```bash
python -m motor_contabil.backup fazer     --dados D:\dados_contabeis --destino E:\backups
python -m motor_contabil.backup testar    --destino E:\backups   # restaura numa pasta temporária e confere
python -m motor_contabil.backup situacao  --destino E:\backups   # sai com erro se a última cópia tem mais de 26 h
python -m motor_contabil.backup restaurar --destino E:\backups --para D:\dados_restaurados
```

Restaurar só funciona numa pasta vazia: feche o aplicativo, restaure numa
pasta nova, confira e só então troque a pasta de dados.

**Agendar no Windows** (Prompt de Comando, ajustando os caminhos; roda todo
dia às 18h e, se o computador estiver desligado nesse horário, na próxima vez
que for ligado):

```bat
schtasks /Create /TN "Backup contabil" /SC DAILY /ST 18:00 /RL LIMITED ^
  /TR "\"C:\caminho\.venv\Scripts\python.exe\" -m motor_contabil.backup fazer --dados D:\dados_contabeis --destino E:\backups"
```

Depois, em Agendador de Tarefas, abra a tarefa, marque "Executar a tarefa o
mais cedo possível após uma inicialização agendada ter sido perdida" e defina
"Iniciar em" como a pasta `automacao-contabil`. A barra lateral do aplicativo
avisa quando a última cópia tem mais de 26 horas.

O destino deve ser outro disco, um pendrive ou uma unidade de rede, e de
preferência guardado fora da sala do computador. Teste a restauração antes do
piloto e depois a cada três meses.

## Dados separados por empresa

Cada empresa cliente tem a sua pasta dentro da pasta de dados do escritório
(`dados/` por padrão, fora do controle de versão):

```
dados/nx/empresa.json   nome, CNPJ, conta do banco, prefixo da marca, formato do plano
dados/nx/plano.csv      plano de contas da empresa
dados/nx/regras.json    regras de classificação da empresa
dados/nx/motor.db       movimentos, lançamentos, lotes e trilha de auditoria
dados/nx/arquivos/      extratos e planilhas lidos com sucesso, como chegaram (por mês)
```

Não há banco compartilhado: o motor de uma empresa só abre a pasta dela, e o
controle de duplicidade é de cada empresa. No cadastro, o plano e as regras são
validados juntos (conta do banco e conta de cada regra precisam existir no
plano e ser analíticas), e CNPJ e prefixo da marca não podem se repetir. Ao
receber um arquivo idêntico a um já guardado em outra empresa, o aplicativo
avisa, porque provavelmente foi enviado na empresa errada.

```bash
python -m motor_contabil.cli --dados dados cadastrar-empresa nx --nome "N X ARAUJO LTDA" \
    --cnpj 62.064.868/0001-02 --conta 362 --prefixo NX --plano plano_fortes.csv --regras regras.json
python -m motor_contabil.cli --dados dados --empresa nx importar extrato.pdf
python -m motor_contabil.cli --dados dados --empresa nx exportar lote.csv
```

Na interface, a empresa é escolhida na barra lateral, e o cadastro também pode
ser feito por lá. O backup copia a pasta `dados/` inteira, com todas as
empresas.
