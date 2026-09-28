# Assistente DIOAC 4B

Configuração de modelo (Open WebUI + `qwen3:4b-instruct` ou equivalente)
para consulta normativa, orientação sobre SIGAA/SEI e elaboração de minutas.

Ver `system-prompt.md` para o prompt de sistema completo e a configuração
de tools/valves recomendada.

## Status

- Escopo atual: consulta normativa + Base de Conhecimento + elaboração de
  minutas.
- SIGAA e SEI: apenas orientação manual (sem integração/API), por decisão
  registrada em 2026-09-28 — não há credenciais/API disponíveis ainda.
- Editor de PDF: é um assistente separado, `Editor PDF DIOAC 4B` (pasta
  `../editor-pdf-dioac-4b`), porque acumular as duas funções em um único
  modelo causava confusão de ferramentas (ver histórico no README daquela
  pasta).

## Próximo passo recomendado

Antes de qualquer ajuste fino de prompt, confirme que a coleção da Base de
Conhecimento no Open WebUI realmente contém os normativos, manuais de
SIGAA/SEI e modelos de minuta que o setor usa — em texto extraível. Sem
isso, o assistente vai (corretamente) responder "não encontrei na base" para
a maioria das perguntas normativas.
