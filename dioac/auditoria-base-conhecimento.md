# Auditoria da Base de Conhecimento DIOAC

Conferência do documento "Base de Conhecimento Acadêmico-Normativo" contra o texto da Resolução 1892-CONSEPE (PDF anexado, 74 p.) e o Guia SIGAA da Coordenação (PDF anexado, 2023).

## O que foi verificado e está correto
- Art. 125 (caput e §§ 1º a 5º), Art. 127, Art. 130 (caput e parágrafo único), Art. 121, 122, 123 e Art. 139 § 1º conferem com o texto da Resolução.
- Art. 115 trata de outra matéria ("dever de verificar a situação de inscrição nas turmas após o processamento"). A regra do prompt de não usá-lo para trancamento está certa.
- O fluxo de readmissão no Guia SIGAA (homologar pagamento/isenção, status volta a ATIVO) confere com o item 3 da base.

## Erros e omissões a corrigir na base
| # | Onde | Problema | Correção |
|---|------|----------|----------|
| 1 | Item 1, Art. 126 | Só o inciso I foi citado. O Art. 126 tem **três** vedações: I (primeiro e último período, salvo em lei), **II (estudantes em Plano de Estudos)** e **III (inadimplentes na Biblioteca e/ou Núcleo de Acessibilidade)**. | Citar os três incisos. A resposta sobre "quem pode trancar" fica incompleta sem o II e o III. |
| 2 | Item 1, Art. 125 | Falta o **§ 6º** (regular com o Núcleo de Acessibilidade = acompanhado pelo núcleo e sem pendência). | Incluir o § 6º. |
| 3 | Item 1, Interpretação | A exceção de saúde para o 1º período é montada com Art. 126 I + Art. 154 par. único + IN. O Art. 154 par. único fala em "gestante, adotante ou portador de afecção que gere incapacidade física relativa" e diz que é *facultado o pedido* de trancamento. Isso não é igual à "incapacidade intelectual e emocional atestada por laudo" do Art. 6º da IN citada. | Separar o que é texto da Resolução do que é da IN, e marcar como interpretação o que é combinação das duas. Rever o "Segurança: Alta". |
| 4 | Item 1, IN "n.º 1.731.344/2023" | O número parece um número de documento SEI, não de Instrução Normativa. A IN não foi anexada, então o Art. 6º citado **não pôde ser conferido**. | Conferir o número correto da IN no SEI e anexar o arquivo à base. |
| 5 | Item 1, passo a passo | O Guia SIGAA anexado **não tem a palavra "trancamento"**. Os menus citados ("Portal do Discente → Ensino → Trancamento de Curso…" e "Portal do Coordenador → Aluno → Trancamento de Curso") não estão em nenhuma das fontes anexadas. No Guia, o portal chama-se "Portal Coord. Graduação". | Confirmar os menus no SIGAA ou marcar como "não conferido nas fontes anexadas". Padronizar para "Portal Coord. Graduação". |
| 6 | Item 3, Art. 131 § 4º | A base atribui à "Resolução 4.347/2026-CONSEPE" uma nova redação com exceções à taxa (cancelamento só pelo inciso IV do art. 127; vulnerabilidade). O texto anexado da Resolução 1892 traz o § 4º **sem essas exceções** e não menciona a 4.347. A Resolução 4.347 também não está na base como arquivo. | Anexar a Resolução 4.347/2026 à base. Enquanto não for anexada, o assistente deve dizer que a exceção vem do resumo e não foi confirmada em texto-fonte. |
| 7 | Item 3, taxa de R$ 100,00 | A Resolução só diz "taxa por meio de GRU" (Art. 131 § 4º, Art. 132). O valor e o prazo de 7 dias vêm da IN 02/2023, que não foi anexada. | Anexar a IN 02/2023-PROEN. |
| 8 | Item 2, desligamento | Está citado só o Art. 138 I. O **Art. 138 II** também gera desligamento (readmissão pedida e **indeferida**), e o Art. 131 § 5º registra o indeferimento. | Acrescentar o Art. 138 II e o Art. 131 § 5º. |
| 9 | Item 3, Art. 131 §§ 2º e 3º | Quem aprecia o pedido: Coordenador para o inciso I do Art. 130; **Colegiado** para os incisos II e III. A base trata o Colegiado de forma genérica. | Citar os §§ 2º e 3º. |
| 10 | Item 3 | Falta o Art. 131 § 6º (prazo de integralização suspenso enquanto o pedido de readmissão tramita). | Incluir. |

## Problemas do prompt original
1. **Contradição**: pede que a fonte esperada seja "Resolução 1892.pdf" e, na mesma frase, proíbe substituir por "Resolução 1892". Isso confunde o modelo. Foi resolvido declarando que as duas grafias são a mesma fonte.
2. **Regra de trancamento fixa demais**: citar o Art. 125 está certo, mas o prompt não manda ler o Art. 126 (vedações), então a resposta sobre trancamento sai sem os incisos II e III.
3. **Sem hierarquia entre resumo e norma**: a base docx é resumo com interpretação. O prompt a trata como fonte principal. Agora o texto da norma prevalece.
4. **Sem instruções de como consultar**: faltava dizer ao modelo para incluir "Art. N" e o assunto na consulta, e quantas tentativas fazer.
5. **Incentivo a respostas longas e burocráticas** (formato extenso sempre). O novo formato começa pela resposta direta.
6. **Referência a arquivo que não está na base** (`RESOLUCAO_3505_2024_CONSEPE.pdf`, `SEI_1892...`). Se o arquivo não existe na base, a menção só gera ruído.

## Como o resgate piora (hipóteses; não consegui testar o Open WebUI)
O `localhost:8080` não é acessível desta sessão, então estas são hipóteses sobre a configuração e não resultados medidos:
- O PDF original, quando lido pelo extrator padrão, repete o cabeçalho "UNIVERSIDADE FEDERAL DO MARANHÃO / Fundação Instituída…" em cada página e separa o número do artigo do texto em colunas. Um pedaço de texto cortado no meio de um artigo perde o número do artigo, e a busca por "Art. 125" falha.
- O número do artigo e o assunto raramente estão no mesmo trecho que o conteúdo. Buscar "Art. 125" só funciona se o número estiver no trecho indexado.
- Busca puramente por embeddings tende a falhar com números ("125" vs "115"); busca híbrida (BM25 + embeddings) lida melhor.

## Ações recomendadas no Open WebUI (nomes conforme a versão; confira em Admin → Configurações → Documentos)
1. Substituir o PDF da Resolução 1892 pelo arquivo `resolucao-1892-por-artigo.md` (gerado aqui: um bloco por artigo, com cabeçalho "Resolução 1892-CONSEPE — Art. N" e capítulo, sem cabeçalhos repetidos de página; o glossário do Anexo II foi separado por termo).
2. Ativar **busca híbrida** e, se disponível, um **modelo de reranking**.
3. Usar um **modelo de embeddings multilíngue** (por exemplo `bge-m3` ou `multilingual-e5`), em vez de um modelo só em inglês.
4. Ajustar o tamanho do trecho para cerca de 800 a 1000 caracteres com sobreposição de 100 a 150 (ou usar divisão por cabeçalhos Markdown, se a versão tiver). Aumentar o **Top K** para cerca de 6 a 10.
5. Anexar à base as normas citadas e ausentes: IN 02/2023-PROEN, a IN do trancamento (confirmar o número) e a Resolução 4.347/2026-CONSEPE. Sem os textos-fonte, o assistente só pode repetir o resumo.
6. Ao reprocessar, **medir**: montar um conjunto de 15 a 20 perguntas com a resposta esperada (artigo correto) e comparar antes e depois. Sugestão de perguntas iniciais: "Quem não pode trancar o curso?", "Qual o limite de trancamentos?", "Quem analisa readmissão por doença grave?", "Posso cancelar disciplina no 1º período?", "Quando ocorre desligamento por não readmissão?".
