# Instruções para os testes no escritório (H1 a H5)

Quem executa: pessoa do escritório com acesso ao Fortes. Quem registra: administrador do app
(**Sessão > Homologação > Registrar resultado de teste**).
Use sempre uma **empresa de teste no Fortes**, nunca uma empresa em produção, até o H1 estar aprovado.
Guarde prints e arquivos reais **fora do repositório** (ele é público).

Preparação, uma vez:

```bash
cd conciliador_fortes
pip install -r requirements.txt
python -m pytest        # todos devem passar; se algo falhar, pare e avise
```

## H4 · Backup e restauração (comece por este; não depende do Fortes)

Com a base real do escritório em uso:

```bash
python scripts/teste_restauracao.py --saida restauracao.json
```

Aprovado quando todas as linhas saem `[OK]` e o resultado é `APROVADO`. O script só lê a pasta de dados e restaura
numa pasta temporária, que apaga no fim. Se avisar que a base só tem usuários de demonstração, o resultado não vale.
Anexe `restauracao.json` como evidência. Copie também a pasta de backups para outro disco.

## H2 · Limite do histórico

1. No Fortes de teste, escolha duas contas analíticas quaisquer (anote os códigos reduzidos).
2. Gere o arquivo de teste (11 linhas de R$ 0,01, históricos de 80 a 200 caracteres):
   ```bash
   python scripts/gerar_lote_homologacao.py --debito 259 --credito 362 --data 01/01/2026 --prefixo HOM
   ```
3. Importe `lote_teste_historico.csv` no Fortes de teste com "Desconsiderar Identificador" e "Utilizar Código Reduzido".
4. Abra o Razão e, para cada linha, preencha em `lote_teste_historico_esperado.csv`: apareceu inteiro? A marca
   `[HOM-...]` ficou no fim? Tire print.
5. O limite validado é o **maior tamanho em que o histórico apareceu inteiro, com a marca**. Configure esse valor
   em Cadastros > Parâmetros. Se o Fortes recusar a importação, anote a mensagem exata.
6. Registre H2 com referência = o número (ex.: `120`) e os prints.

## H3 · Razão real

1. No Fortes, exporte o Razão da conta do banco (a opção que o escritório usa) para CSV ou planilha.
2. Anonimize o que for necessário. Abra o arquivo e verifique as colunas: data, conta, débito, crédito, histórico.
3. Carregue em Cadastros > Razão. O formato `fortes_importacao` só serve para arquivos no leiaute de importação;
   para um Razão exportado, use `tabular` e mapeie as colunas.
4. Compare o saldo do banco que o app mostra na Conferência com o saldo no Fortes na mesma data.
   Se não bater, **não aprove**: anote o que difere (sinal, saldo inicial, formato de data/valor) e me envie o arquivo
   anonimizado para ajustar o leitor.
5. Registre H3 com referência = `tabular` (ou `fortes_importacao`) e o print do saldo.

## H5 · Extratos reais do piloto

Para cada banco do piloto: carregue um OFX e um CSV/XLSX reais numa empresa de teste do app. Aprovado quando o
arquivo carrega sem erro estrutural e o saldo final calculado bate com o do extrato (Conferência). Anote os bancos
e os formatos. Registre H5 com a lista na referência.

## H1 · Importar um lote real

Pré-requisitos: H2 e H3 ao menos em teste.

1. No app, numa empresa de teste, classifique um mês pequeno e gere o lote.
2. Importe o arquivo no Fortes de teste. Registre o retorno no app: "Importado sem erro", ou "Rejeitado" com a
   mensagem exata do Fortes (isso vira falha e ação corretiva).
3. Exporte o Razão do Fortes **depois** da importação, carregue em Cadastros > Razão e clique em
   **Conferir lote no Razão**. Aprovado quando: nenhuma marca ausente, nenhuma duplicada, nenhuma divergência.
4. Tente importar o mesmo arquivo de novo e anote se o Fortes recusa ou duplica (informação útil; o app já bloqueia
   novo lote com os mesmos movimentos).
5. Registre H1 com referência `slug-da-empresa:id-do-lote` e prints da importação e do Razão.

## Depois dos testes

Rode `python scripts/relatorio_homologacao.py` para atualizar o relatório. A integração só aparece como liberada
quando H1 a H5 estiverem aprovados. Reprovação não é problema: registre a falha e a ação corretiva e repita.
