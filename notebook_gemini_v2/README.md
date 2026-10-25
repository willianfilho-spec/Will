# Notebook de Pesquisa com Gemini — versão 2 (em desenvolvimento)

Estado: **fases 0 a 3 de 10**. Veja a tabela de estado no final.

## Instalar e abrir (Windows 11)

1. Instale o Python 3.11 ou mais novo em https://www.python.org/downloads/ e marque **Add python.exe to PATH**.
2. Dê dois cliques em `run.bat`. Na primeira vez ele cria o ambiente, instala as dependências e cria o arquivo `.env`.
3. Abra o `.env` no Bloco de Notas e troque `cole_sua_chave_aqui` pela sua chave (https://aistudio.google.com/apikey). Nunca compartilhe esse arquivo.
4. O navegador abre sozinho. Se não abrir, acesse http://localhost:8501.

A chave é necessária para indexar e perguntar. Importar e conferir documentos funciona sem ela.

O modelo de embeddings (`GEMINI_EMBEDDING_MODEL`) vem com um valor padrão **não verificado** por este projeto. Confirme o nome na documentação do Google e no catálogo da sua conta antes de usar. Se mudar o modelo ou `EMBEDDING_DIM`, reindexe (o app avisa).

## O que já funciona

- Criar notebooks (persistem após reiniciar).
- Importar PDF, DOCX, PPTX (cada slide vira uma página), TXT, MD e CSV, com limite de tamanho (`MAX_UPLOAD_MB`, padrão 50).
- Guardar o texto **por página** (PDF). A página é a posição física no arquivo (1 = primeira folha), que pode ser diferente do número impresso na folha.
- Recusar duplicados (mesmo conteúdo no mesmo notebook, mesmo com outro nome).
- Detectar PDF sem texto (digitalizado). Se for inteiro, é recusado com orientação de OCR. Se só algumas páginas estiverem sem texto, o arquivo entra com aviso listando quais.
- **Busca semântica (fase 2):** os documentos são divididos em trechos (sem atravessar páginas, sem cabeçalhos e rodapés repetidos), cada trecho recebe um vetor (embedding) do Gemini, e a pergunta traz só os N trechos mais parecidos (você escolhe N). Só esses trechos vão ao Gemini. Documentos do tipo `referencia` ou `material` ficam fora da busca.
- **Citações conferidas (fase 3):** o Gemini responde em formato estruturado: cada afirmação é *documentada* (com citação literal), *inferência* ou *recomendação*. O programa confere sozinho se a citação literal existe no trecho indicado (ignorando acentos, espaços e hifenização do PDF), aponta quando ela está em outro trecho, quando é inventada ou alterada, e alerta se o texto cita página, artigo ou número que não aparece nos trechos citados. A página exibida vem do trecho recuperado, nunca do texto do modelo. Cada citação tem "Conferir": mostra o trecho, a página original do PDF como imagem e o download do arquivo.
- Cada pergunta é gravada com os trechos recuperados e o resultado da verificação, para auditoria posterior.
- Pré-visualizar o texto extraído de cada página, para você conferir com o original.
- Corrigir texto embaralhado de títulos com sombra/contorno (letras repetidas), relendo a página com um segundo extrator.

## Importar vários arquivos de uma vez (sem abrir o navegador)

No terminal, dentro da pasta do projeto, com o ambiente ativado (`.venv\Scripts\activate`):

```
python importar.py "Normas da Graduação" "C:\pasta\base.md" "C:\pasta\guia.pdf"
```

Se o notebook já existir, os arquivos entram nele. Arquivos repetidos são ignorados.

## Como preparar PDFs digitalizados

Aplique OCR antes de enviar, com uma ferramenta aprovada pela sua instituição, e salve um PDF **com camada de texto**. Depois do OCR, confira artigos, números, tabelas e notas na pré-visualização: o reconhecimento erra justamente nesses pontos.

## Rodar os testes

```
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest
```

## Estado dos requisitos

| Requisito | Estado |
|---|---|
| Notebooks persistentes, importação com páginas, duplicados, limite de tamanho, detecção de PDF sem texto | Implementado e testado (fases 0 e 1) |
| Busca semântica (RAG): trechos, embeddings, recuperação, top-k ajustável | Implementado e testado com embeddings simulados. **Não testado com a API real do Gemini** |
| Referências verificáveis (arquivo, página, trecho; marcadores ligados aos trechos; documentada × inferência × recomendação) | Implementado e testado com respostas simuladas. **Não testado com a resposta real do Gemini** |
| Declarar insuficiência de evidência | Parcial: o modelo declara e a tela exibe; o corte automático por similaridade é a fase 4 |
| Login, perfis, isolamento por usuário | Pendente (fase 5) |
| Auditoria | Pendente (fase 6) |
| Backup e recuperação | Pendente (fase 8) |
| OCR integrado | Futuro. Hoje só há detecção e orientação |

## Limitações atuais

- **PDF que parece ter texto mas não tem todo o texto não é detectado.** Se a maior parte do conteúdo estiver desenhada como imagem ou contorno (ex.: PDFs impressos de páginas web), só os títulos e rodapés entram, e o app não avisa. Confira sempre a pré-visualização. Uma checagem de cobertura está prevista na fase de OCR.
- Alguns PDFs (ex.: a Resolução 1.892/2019, cerca de 190 casos em 74 páginas) saem com espaços indevidos no meio de palavras ("efeti vada") por causa do espaçamento do arquivo. Para conferir uma citação, compare ignorando espaços.
- PPTX (PowerPoint) ainda não é suportado; exporte para PDF.
- **Não há login.** Qualquer pessoa que abrir o app vê todos os notebooks. Use só no seu computador.
- **Citação confirmada não é conclusão correta.** A verificação prova que o texto citado existe no trecho, não que ele sustente a afirmação nem que seja a norma vigente. Confira no original.
- Se o modelo não responder no formato estruturado, nenhuma citação é verificada e a tela avisa.
- Paráfrases marcadas como "documentada" são reprovadas de propósito: só citação literal conta como documentada.
- A página renderizada é a numeração física do PDF; DOCX e PPTX só oferecem o download.
- A qualidade da busca com o Gemini real não foi medida. Nos testes offline, só a coincidência de palavras foi avaliada.
- Não há busca por palavra exata (ex.: "Art. 151") combinada com a semântica; está nos planos futuros.
- Um artigo que continua na página seguinte vira trechos separados por página.
- Nenhuma chamada real à API do Gemini foi feita (sem chave neste ambiente), nem para embeddings, nem para respostas.
- O `run.bat` não foi testado em Windows (só em Linux).
- Um DOCX malicioso muito compactado pode consumir memória; não envie arquivos de origem desconhecida.
- O texto enviado ao Gemini sai do seu computador. Não use documentos institucionais sem autorização e avaliação de proteção de dados.
