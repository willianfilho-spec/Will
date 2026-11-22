# Instruções para agentes de código (Codex e similares)

Este diretório contém o motor de automação de lançamentos contábeis a partir
de extratos bancários. Leia o `README.md` antes de alterar qualquer coisa.

## Preparar o ambiente e testar

```bash
cd automacao-contabil
pip install pytest            # suficiente para os testes
pip install -r requirements.txt   # completo (interface Streamlit e SDK de IA)
pytest
```

Todos os testes precisam passar antes de qualquer commit. O núcleo
(`motor_contabil/`) usa só a biblioteca padrão do Python; não adicione
dependências a ele sem necessidade clara. Exceções, importadas só quando a
função é usada: `pdfplumber` (extrato Itaú em PDF), `reportlab`
(relatórios em PDF) e `PyJWT` (login pelo Cloudflare Access).

## Regras que não podem ser quebradas

Estas regras são a razão de existir do projeto. Uma mudança que viole
qualquer uma delas está errada, mesmo que os testes passem.

1. **Nenhum lançamento duplicado.** A chave de idempotência
   (`idempotencia.py`) é a chave primária da tabela `transacoes`. Não troque
   por verificação só no código, não remova a `chave_conteudo` (ela segura
   bancos que mudam o FITID) e não elimine operações apenas porque têm mesma
   data e valor: duas operações iguais podem ser legítimas e vão para revisão.
2. **A IA só sugere.** Lançamento classificado por IA fica sempre `pendente`
   até aprovação humana. A resposta da IA é validada contra o plano de contas
   pelo motor, mesmo com a restrição no esquema JSON.
3. **Valores em `Decimal`, nunca `float`.** Nenhum valor pode mudar entre o
   extrato e o arquivo exportado.
4. **Exportar não repete lançamentos.** Só saem lançamentos `liberado`; ao
   sair, viram `exportado` na mesma transação do banco de dados. Lançamento
   exportado não pode ser alterado nem liberado de novo. Para recuperar um
   arquivo, use `Motor.reexportar`.
5. **Trilha de auditoria.** Toda importação, aprovação, descarte, exportação
   e download registra um evento na tabela `eventos`.
6. **Regras conflitantes não se resolvem sozinhas.** Se duas regras apontam
   contas diferentes, o lançamento vai para revisão. A ordem das regras não
   decide.
7. **Minimização de dados.** Para a IA vão apenas o histórico (com CPF/CNPJ
   mascarados) e o sentido da operação. Não envie valor, data, conta bancária
   ou extrato inteiro sem decisão explícita dos responsáveis.

Ao mudar comportamento coberto por essas regras, adicione ou ajuste testes
em `testes/test_motor.py` que provem que a regra continua valendo.

## Pontos ainda indefinidos (não invente)

- **Leiaute de exportação:** o Fortes tem exportador próprio
  (`exportador_fortes.py`), tirado de arquivos reais aceitos pelo sistema e
  protegido por `test_leiaute_fortes_byte_a_byte`. Não altere esse leiaute sem
  um novo arquivo real aceito pelo Fortes. Para outro sistema (Domínio,
  Alterdata, SCI), crie um exportador novo só a partir da documentação oficial
  ou de um arquivo real aceito, mantendo a interface
  `escrever(lancamentos, destino)`. `exportador.py` continua como CSV genérico.
- **Provedor de IA:** o classificador atual usa a API da Anthropic. Para usar
  outro provedor, crie uma nova classe que implemente o protocolo
  `Classificador` (`sugerir(transacao, plano) -> Sugestao | None`) e mantenha
  as regras 2 e 7. Não remova a implementação existente sem decisão da equipe.
- **Conciliação bancária:** gerar lançamentos a partir do extrato não é
  conciliar. A conciliação é a conferência de `conciliacao.py` (extrato
  completo x arquivos importados no Fortes). Ela ainda não lê o razão emitido
  pelo Fortes; não a descreva como conferência do razão.
- **Dados por empresa:** cada empresa tem pasta própria em `dados/`
  (`empresas.py`). Não crie banco compartilhado entre empresas.

## Acesso

- No modo remoto (`acesso.py`), a identidade vem só de token do Cloudflare
  Access com assinatura conferida. Não aceite e-mail de cabeçalho sem token,
  não desligue a conferência de público (AUD) ou emissor e não libere acesso
  sem token fora de `localhost`.

## Dados

Os arquivos em `exemplos/` são fictícios. Nunca faça commit de extratos
reais, planos de contas de clientes ou arquivos `.db` (já estão no
`.gitignore`).

## Estilo

Código, comentários, mensagens ao usuário e documentação em português do
Brasil. Mensagens de erro devem dizer o que fazer, não só o que falhou.
