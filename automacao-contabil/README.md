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
| Lê OFX (1.x e 2.x) e CSV de extrato | Ler PDF, Excel (.xlsx) ou relatórios de sistemas |
| Impede lançamento duplicado ao reprocessar ou sobrepor extratos | Conciliação bancária completa (confronto com a contabilidade já escriturada) |
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
trilha de auditoria.

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
5. Separar a base de dados por empresa cliente.
