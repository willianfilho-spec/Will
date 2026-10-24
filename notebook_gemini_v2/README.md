# Notebook de Pesquisa com Gemini — versão 2 (em desenvolvimento)

Estado: **fases 0 e 1 de 10**. Veja a tabela de estado no final.

## Instalar e abrir (Windows 11)

1. Instale o Python 3.11 ou mais novo em https://www.python.org/downloads/ e marque **Add python.exe to PATH**.
2. Dê dois cliques em `run.bat`. Na primeira vez ele cria o ambiente, instala as dependências e cria o arquivo `.env`.
3. Abra o `.env` no Bloco de Notas e troque `cole_sua_chave_aqui` pela sua chave (https://aistudio.google.com/apikey). Nunca compartilhe esse arquivo.
4. O navegador abre sozinho. Se não abrir, acesse http://localhost:8501.

A chave só é necessária para a aba "Perguntar ao Gemini". Importar e conferir documentos funciona sem ela.

## O que já funciona

- Criar notebooks (persistem após reiniciar).
- Importar PDF, DOCX, TXT, MD e CSV, com limite de tamanho (`MAX_UPLOAD_MB`, padrão 50).
- Guardar o texto **por página** (PDF). A página é a posição física no arquivo (1 = primeira folha), que pode ser diferente do número impresso na folha.
- Recusar duplicados (mesmo conteúdo no mesmo notebook, mesmo com outro nome).
- Detectar PDF sem texto (digitalizado). Se for inteiro, é recusado com orientação de OCR. Se só algumas páginas estiverem sem texto, o arquivo entra com aviso listando quais.
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
| Busca semântica (RAG) com embeddings | Pendente (fase 2) |
| Referências verificáveis (arquivo, página, trecho) | Pendente (fases 3 e 4) |
| Login, perfis, isolamento por usuário | Pendente (fase 5) |
| Auditoria | Pendente (fase 6) |
| Backup e recuperação | Pendente (fase 8) |
| OCR integrado | Futuro. Hoje só há detecção e orientação |

## Limitações atuais

- **PDF que parece ter texto mas não tem todo o texto não é detectado.** Se a maior parte do conteúdo estiver desenhada como imagem ou contorno (ex.: PDFs impressos de páginas web), só os títulos e rodapés entram, e o app não avisa. Confira sempre a pré-visualização. Uma checagem de cobertura está prevista na fase de OCR.
- PPTX (PowerPoint) ainda não é suportado; exporte para PDF.
- **Não há login.** Qualquer pessoa que abrir o app vê todos os notebooks. Use só no seu computador.
- A aba "Perguntar ao Gemini" ainda é a consulta simples da v1: envia o início de cada documento ao modelo. **As citações dela não são verificadas.**
- Não foi testada com a API real do Gemini.
- O `run.bat` não foi testado em Windows (só em Linux).
- Um DOCX malicioso muito compactado pode consumir memória; não envie arquivos de origem desconhecida.
- O texto enviado ao Gemini sai do seu computador. Não use documentos institucionais sem autorização e avaliação de proteção de dados.
