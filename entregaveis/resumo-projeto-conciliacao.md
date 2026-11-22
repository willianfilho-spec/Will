# Projeto — Agente de Conciliação Bancária e Integração por Arquivo com o Fortes

## 1. Objetivo

Desenvolver e validar um aplicativo web para receber arquivos dos clientes, apoiar a classificação e a conciliação contábil e gerar arquivos de importação para o Fortes. O contador mantém a responsabilidade pelas decisões e aprovações.

Este resumo consolida o projeto original e as recomendações discutidas. As escolhas de arquitetura abaixo são propostas para o piloto; não representam recursos já implementados ou serviços contratados.

## 2. Usuários e responsabilidades

- **Clientes convidados:** enviam documentos e acompanham recebimentos e pendências somente das empresas autorizadas.
- **Equipe contábil — Daiane, Luciana e Willian:** importa documentos contábeis, classifica, concilia, corrige propostas e mantém regras conforme suas permissões.
- **Revisor contábil:** realiza a segunda confirmação de itens de risco; pode ter essa permissão sem poder autorizar a exportação.
- **Responsável autorizado:** aprova e libera a exportação dos lotes. A importação no Fortes permanece manual.

## 3. Entradas e saídas

### Entradas

- Extratos bancários em OFX, CSV ou XLSX.
- Planilhas de despesas em XLSX ou CSV.
- Plano de contas exportado do Fortes.
- Razão ou balancete do período.
- Regras de classificação específicas de cada empresa.

Priorizar formatos estruturados no piloto. Leitura de PDF e OCR ficam para uma etapa posterior, após validação dos leitores e da qualidade da extração.

### Saídas

- Fila de revisão com classificações, justificativas e pendências.
- Relatório de possíveis duplicidades e contas ausentes.
- Conferência mensal entre extrato e contabilidade.
- Arquivo de importação no leiaute aceito pelo Fortes.
- Histórico de aprovações, alterações, exportações e resultado informado da importação.

## 4. Funcionamento

1. Cliente envia arquivos para a empresa e o período autorizados.
2. Aplicativo valida formato, datas, valores e campos obrigatórios.
3. Movimentos são normalizados e comparados com cargas anteriores.
4. Motor aplica as regras da empresa.
5. Itens sem regra seguem para classificação manual ou sugestão opcional de IA.
6. Equipe revisa e corrige as propostas; itens de risco recebem segunda confirmação.
7. Sistema valida contas, partidas e leiaute e apresenta a conferência de saldo.
8. Responsável autorizado libera a exportação.
9. Aplicativo guarda o lote e permite baixar o arquivo.
10. Pessoa importa no Fortes e registra a aceitação ou rejeição.

O projeto original permite exportar com diferença de saldo destacada e registrada. Para diferenças sem explicação comprovada, a recomendação é exigir segunda revisão e nunca declarar a conciliação concluída.

## 5. Regras contábeis e uso de IA

- Cálculos, valores monetários, saldos, validação de contas e exportação são executados por código; valores monetários usam representação decimal exata.
- Regras do escritório têm prioridade na classificação recorrente.
- IA apenas sugere classificações, novas regras e explicações; não aprova nem escreve no Fortes.
- Toda sugestão da IA exige aprovação humana antes da exportação.
- Só podem ser utilizadas contas existentes no plano vigente da empresa.
- Movimentos de sócios, partes relacionadas, natureza incerta e tributos com possíveis multas ou juros exigem decisão contábil.
- Transferências entre contas exigem tratamento e conferência específicos.
- Movimentos iguais podem ser legítimos: semelhança gera alerta, não exclusão automática.
- Instruções encontradas dentro de documentos são tratadas como conteúdo do arquivo, nunca como comandos para o agente.
- O sistema deve continuar funcionando sem IA. No início, mantê-la desativada evita cobrança de API.

## 6. Aprovação e segunda revisão

Permitir que o responsável autorizado aprove o próprio trabalho em itens rotineiros, preservando o histórico.

Exigir confirmação de outra pessoa habilitada para:

- Movimentos de sócios e partes relacionadas.
- Natureza contábil incerta.
- Possível duplicidade que se decidiu manter.
- Exportação com diferença de saldo sem explicação comprovada.
- Movimentos a partir de **R$ 10 mil**, como limite inicial proposto, ajustável por empresa após o piloto.

O limite de R$ 10 mil é uma proposta operacional, não uma exigência legal ou parâmetro aprovado. Se não houver outro revisor disponível, o item de risco fica pendente e os demais podem seguir em lote separado.

## 7. Arquitetura e piloto sem custo inicial de serviços

### Etapa A — Validação interna

| Componente | Proposta |
|---|---|
| Interface | Streamlit + Python, no computador do escritório |
| Acesso | Navegador local |
| Banco | SQLite separado por empresa |
| Arquivos | Pastas locais separadas por empresa |
| Classificação | Regras e revisão manual; IA opcional |
| Operação inicial | Uma pessoa por vez revisando e exportando |
| Backup | Cópia para outro dispositivo já disponível e teste de restauração |

Esta etapa valida o motor com arquivos de clientes, mas não oferece acesso direto dos clientes pela internet. O cliente envia documentos pelos canais atuais e a equipe os carrega no aplicativo.

### Etapa B — Piloto externo com clientes

O objetivo também inclui clientes entrando pelo próprio navegador e enviando arquivos. Portanto, o piloto completo precisa desta etapa.

| Componente | Proposta a verificar |
|---|---|
| Interface hospedada | Streamlit em hospedagem gratuita compatível, como Community Cloud |
| Autenticação | Supabase Auth ou serviço equivalente, inicialmente em plano gratuito |
| Banco | PostgreSQL gerenciado em plano gratuito |
| Arquivos | Armazenamento privado e persistente, com políticas por empresa |
| Participantes | Um ou dois clientes convidados |
| Primeiros documentos | Fictícios, antes de usar documentos reais |

Não depender do disco local da hospedagem para persistir arquivos ou banco. A separação entre clientes deve ser aplicada no acesso ao banco e aos arquivos, além da interface.

**Meta financeira:** custo inicial de serviços igual a zero, condicionado à verificação dos limites, recursos e condições dos planos gratuitos. Desenvolvimento, configuração, equipamentos existentes e tempo da equipe continuam sendo necessários. Serviços gratuitos podem ter suspensão por inatividade, cotas e limitações de recuperação; não presumir recursos de planos pagos.

Antes de documentos reais, verificar autenticação, isolamento entre empresas, acesso privado aos arquivos, permissões e restauração de backup.

### Evolução após o piloto

- Manter Streamlit enquanto atender ao fluxo; avaliar outra interface se necessário.
- Adotar PostgreSQL gerenciado pago e armazenamento privado com recuperação adequada ao uso.
- Considerar Supabase para reunir autenticação, PostgreSQL e arquivos, após comparação de recursos e custos vigentes.
- Avaliar recuperação para um ponto no tempo — PITR — com pelo menos sete dias de janela, como proposta para a operação posterior.
- Confirmar separadamente a cobertura de backup dos arquivos: backup do banco não significa backup dos documentos.

## 8. Autenticação e controle de acesso

- Acesso somente por convite.
- Preferir serviço gerenciado, sem implementar armazenamento próprio de senhas.
- Oferecer opção por e-mail e, quando conveniente, Google ou Microsoft, evitando obrigar todos os clientes a criar contas nesses provedores.
- Verificar o suporte de autenticação da versão do Streamlit e a integração escolhida.
- Recomendar segundo fator para equipe e clientes, com recuperação de acesso. Confirmar suporte e custo no plano selecionado antes de tratá-lo como implementado.
- Login identifica a pessoa; permissões determinam empresas e ações autorizadas.
- Segundo fator na conta pessoal do provedor não deve ser presumido como uma exigência controlada pelo aplicativo. Um serviço de autenticação com MFA próprio pode permitir esse controle.

## 9. Retenção, exclusão e backups

| Categoria | Proposta inicial |
|---|---|
| Registros de acesso e segurança | 12 meses, sem senhas, tokens ou conteúdo documental |
| Arquivos temporários e uploads recusados | Até 30 dias, salvo necessidade documentada |
| Documentos contábeis de origem | Prazo por categoria, obrigação aplicável e contrato |
| Aprovações, alterações, regras utilizadas e lotes | Guarda coerente com a documentação e os lançamentos que sustentam |
| Backups para operação posterior | 30 cópias diárias e 12 mensais, com expiração automática |

Esses prazos operacionais são propostas e não substituem a definição das obrigações legais de guarda. Não aplicar um prazo genérico único a todos os documentos.

- Definir início da contagem, responsáveis e procedimento de descarte.
- Suspender exclusões pertinentes quando houver fiscalização, disputa ou outra obrigação de preservação.
- Informar que dados excluídos do sistema ativo podem permanecer nos backups até a expiração, por até 12 meses na política proposta.
- Após restauração, reaplicar as exclusões registradas antes de liberar o acesso.
- Testar a restauração antes do piloto e, como rotina proposta, a cada três meses.
- Backup é mecanismo de recuperação; não substitui o arquivo oficial dos documentos.
- No piloto gratuito, implementar e testar a estratégia disponível, sem prometer automaticamente a retenção e o PITR de planos pagos.

## 10. Fortes e integridade dos lotes

- Confirmar o leiaute com um arquivo de referência já aceito pelo Fortes.
- O documento original descreve nove campos, sem cabeçalho, separados por ponto e vírgula, datas em `dd/mm/aaaa` e vírgula decimal; validar sua aplicação a cada cliente.
- Histórico em maiúsculas, sem acentos e com até 118 caracteres, conforme especificação original a conferir.
- Arquivo gerado pelo código, nunca diretamente pelo modelo de IA.
- Exportação transacional: falha não pode deixar lote parcial marcado como exportado.
- Guardar os bytes originais do lote para reproduzir exatamente uma reexportação.
- Diferenciar carregado, aprovado, exportado e importado no Fortes; exportação não comprova importação.
- Definir fluxo de correção de lote rejeitado sem duplicar lançamentos.

## 11. Critérios de validação

- Valores e movimentos corretamente lidos nos formatos suportados.
- Nenhuma perda silenciosa de movimentos ou conta inexistente.
- Nenhuma duplicação de lançamento por reenvio ou exportação concorrente.
- Repetições legítimas preservadas e sinalizadas.
- Nenhuma sugestão de IA exportada sem aprovação.
- Arquivo aceito pelo Fortes sem linhas rejeitadas.
- Saldo mensal conciliado ao centavo no caso de referência completo.
- Cliente sem acesso a documentos ou dados de outra empresa.
- Backup restaurado com sucesso.
- Tempo de trabalho comparado ao processo manual.
- Meta inicial de 70% dos movimentos classificados por regras após três meses por cliente, a calibrar.

Para IA, usar casos reais já classificados como referência e avaliar separadamente acertos, erros com alta confiança, encaminhamentos corretos para revisão e custo. O projeto original propõe pelo menos 95% de acerto nas sugestões de alta confiança; a meta precisa ser validada em amostra independente.

## 12. Marcos propostos

1. **Conferir o código existente:** verificar Streamlit, leitores, SQLite, exportação e testes mencionados no histórico.
2. **Validar dados e exportação:** reproduzir um mês já fechado e gerar lote aceito pelo Fortes.
3. **Validar regras e conciliação:** revisão humana, duplicidades e painel de saldo.
4. **Executar piloto interno:** processar um mês novo e medir esforço e qualidade.
5. **Preparar acesso externo gratuito:** autenticação, banco, armazenamento privado e isolamento por empresa.
6. **Testar com clientes e dados fictícios:** validar convite, login, upload e permissões.
7. **Liberar piloto limitado com dados reais:** após os controles e a recuperação serem verificados.
8. **Avaliar IA opcional:** somente após definir provedor, uso de dados e orçamento.
9. **Decidir continuidade:** ajustar regras, incluir outro cliente e avaliar plano pago conforme uso.

## 13. Fora do escopo inicial

- Integração automática que importe, altere ou exclua lançamentos no Fortes.
- Apuração de tributos, cálculo de folha, pareceres e fechamento autônomo.
- Decisão automática sobre natureza societária ou fiscal.
- Múltiplos agentes, MCP e banco vetorial.
- OCR e suporte amplo a PDFs bancários na primeira entrega.

## 14. Pendências antes da implementação externa

- Acesso ao repositório e confirmação do que já funciona; este resumo não verifica o código nem os testes anteriores.
- Arquivos de exemplo e leiaute do Fortes aceito para o piloto.
- Escolha final dos serviços gratuitos e verificação atual de cotas, MFA, persistência, região e backup.
- Matriz nominal de permissões e designação de pelo menos dois revisores habilitados.
- Aprovação ou ajuste do limite provisório de R$ 10 mil.
- Tabela de retenção por categoria e contrato.
- Política de privacidade, exclusão e tratamento de dados no piloto.
- Decisão sobre envio de dados a provedor externo de IA.
- Critérios para migrar de planos gratuitos para pagos.

## 15. Recomendação consolidada

Começar validando o motor localmente, sem IA paga. Em seguida, executar um piloto externo pequeno, com serviços gratuitos verificados, para que os próprios clientes façam login e upload. Usar documentos fictícios primeiro e documentos reais somente após confirmar isolamento, permissões e recuperação. Migrar a infraestrutura conforme os resultados e o volume, mantendo aprovação humana e importação manual no Fortes.
