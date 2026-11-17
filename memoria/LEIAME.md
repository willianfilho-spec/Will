# Sistema de memória persistente

Este arquivo documenta o sistema: como ele funciona, como testar, como diagnosticar e como desativar. Não é memória e não é carregado automaticamente.

## Por que fica no repositório

As sessões do Claude Code na nuvem rodam em containers descartáveis. O que fica em `~/.claude` some ao fim da sessão; o repositório é clonado de novo a cada sessão. Por isso memória, instruções e hooks são versionados aqui. **Sem commit + push, nada persiste.**

## Peças

| Arquivo | Função | Carregamento |
|---|---|---|
| `CLAUDE.md` | Regras de uso da memória | Automático (recurso nativo do Claude Code) |
| `memoria/preferencias.md` | Preferências duradouras de comunicação e qualidade | Automático, via `@import` no CLAUDE.md |
| `memoria/pendencias.md` | Itens abertos (P-XXX) | Automático, via `@import` |
| `memoria/projetos.md` | Estado e próximos passos de cada projeto | Sob demanda |
| `memoria/decisoes.md` | Decisões (D-XXX) com justificativa e status | Sob demanda |
| `memoria/usuario.md` | Contexto funcional, só o que já é público | Sob demanda |
| `memoria/historico.md` | Uma linha por mudança relevante | Raramente |
| `.claude/settings.json` | Registra os hooks do projeto | Automático |
| `.claude/hooks/memoria.py` | Hooks `inicio`/`fim` e verificador | Pelos hooks ou manual |
| `.claude/skills/salvar-memoria/` | Procedimento de consolidação (`/salvar-memoria`) | Quando invocada |

`pessoas.md` não existe de propósito: o repositório é público (decisão D-002).

## Fluxo

1. **Início** (`SessionStart`: startup, resume, clear, compact): o Claude Code carrega `CLAUDE.md` e os dois imports. O hook acrescenta ao contexto o estado de cada arquivo (linhas, data mais recente, avisos de tamanho, desatualização, duplicatas e dados sensíveis) e guarda o commit inicial da sessão em `/tmp/claude-memoria/<sessão>/`.
2. **Durante**: o Claude registra o que for durável seguindo as regras do `CLAUDE.md`.
3. **Fim de turno** (`Stop`): se a sessão alterou arquivos fora de `memoria/` (commits desde o início ou mudanças não commitadas) e `memoria/` não foi tocada, o hook pede uma revisão. Isso acontece **no máximo uma vez por sessão** e nunca enquanto o Claude já responde a um bloqueio (`stop_hook_active`).
4. **Consolidação**: o Claude segue a skill `salvar-memoria` (comparar, deduplicar, verificar, commitar, informar).

Os hooks não leem a conversa. Quem decide o que é durável é o modelo; o hook só lembra e verifica.

## Comandos

```bash
python3 .claude/hooks/memoria.py verificar
```

```bash
echo '{"session_id":"teste","source":"startup"}' | python3 .claude/hooks/memoria.py inicio
```

```bash
cat /tmp/claude-memoria/hooks.log
```

## Diagnóstico

- **Hook não roda**: confira `/hooks` dentro do Claude Code e se `python3` existe. Hooks de projeto só valem para sessões abertas numa branch que contenha `.claude/settings.json`.
- **Memória "esquecida"**: a sessão foi aberta numa branch sem os arquivos, ou a última sessão não fez push.
- **Erro do verificador**: remova o dado sensível apontado; se ele já foi enviado ao GitHub, apagar o arquivo não basta, porque continua no histórico do git.
- Falhas dos hooks são silenciosas para não travar o Claude; o motivo fica em `/tmp/claude-memoria/hooks.log` (efêmero).

## Restaurar e desativar

- Restaurar versão anterior de um arquivo: `git log -- memoria/<arquivo>` e `git checkout <commit> -- memoria/<arquivo>`.
- Desativar só a automação: remova o bloco `hooks` de `.claude/settings.json`. A memória continua sendo lida via `CLAUDE.md`.
- Desativar tudo: apague `CLAUDE.md`, `memoria/`, `.claude/hooks/memoria.py`, `.claude/settings.json` e `.claude/skills/salvar-memoria/`.

## Manutenção

- Limites: 80 linhas para os arquivos importados, 250 para os demais. O verificador avisa quando passam.
- `pendencias.md` e `projetos.md` sem data nova há mais de 60 dias geram aviso de desatualização.
- Compactar = resumir itens antigos de histórico e projetos encerrados. Decisões nunca são apagadas, só marcadas como substituídas.
