"""Conciliação movimento a movimento: extrato x Razão da conta do banco.

Procedimento (etapa 2 do fluxo do escritório):
1. casa pela marca [PREFIXO-AAAAMM-NNNNNN] quando o Razão a traz (lote do próprio app);
2. o que sobrou casa pela chave (data, sentido, valor), um para um;
3. cada diferença é classificada:
   - duplicidade_no_razao: o Razão tem mais partidas com a mesma chave do que o extrato;
   - extrato_sem_lancamento: movimento do extrato sem partida no Razão;
   - lancamento_sem_extrato: partida no Razão sem movimento no extrato;
   - divergente: a marca casou, mas data ou valor diferem.
Determinístico: a mesma entrada dá sempre o mesmo resultado. Não altera nenhum dado.
"""

from __future__ import annotations

from collections import defaultdict

from domain.operacoes import Contexto, MARCA_RE, OperacaoInvalida, limites_periodo
from exporters import fortes_exporter
from storage import audit


def comparar(ctx: Contexto, periodo: str, conta_banco: str) -> dict:
    ctx.exigir("conciliar")
    ini, fim = limites_periodo(periodo)
    c = ctx.con.execute("SELECT classificacao FROM plano_contas WHERE vigente = 1 AND reduzido = ?",
                        (conta_banco,)).fetchone()
    contas = [conta_banco] + ([c["classificacao"]] if c else [])
    marks = ",".join("?" * len(contas))
    razao = ctx.con.execute(
        f"SELECT id, data, debito_centavos - credito_centavos AS v, historico FROM razao WHERE conta IN ({marks}) "
        "AND data BETWEEN ? AND ? ORDER BY data, id", (*contas, ini, fim)).fetchall()
    if not razao and not ctx.con.execute("SELECT 1 FROM razao LIMIT 1").fetchone():
        raise OperacaoInvalida("carregue o Razão antes de conciliar o extrato")
    extrato = ctx.con.execute(
        "SELECT id, data, valor_centavos AS v, historico, marca FROM movimentos WHERE conta_banco = ? "
        "AND data BETWEEN ? AND ? AND status <> 'descartado' ORDER BY data, id", (conta_banco, ini, fim)).fetchall()

    r_por_marca: dict[str, list] = defaultdict(list)
    for r in razao:
        for mk in set(MARCA_RE.findall(r["historico"] or "")):
            r_por_marca[mk].append(r)
    usados_razao: set[int] = set()
    casados, divergentes, restantes = [], [], []
    for m in extrato:
        mk = m["marca"] or fortes_exporter.marca(ctx.prefixo, m["data"], m["id"])
        cand = [r for r in r_por_marca.get(mk, []) if r["id"] not in usados_razao]
        if cand:
            r = cand[0]
            usados_razao.add(r["id"])
            if r["data"] == m["data"] and r["v"] == m["v"]:
                casados.append((m["id"], r["id"], "marca"))
            else:
                divergentes.append({"movimento": m["id"], "razao": r["id"], "extrato": (m["data"], m["v"]),
                                    "razao_valor": (r["data"], r["v"])})
        else:
            restantes.append(m)
    livres: dict[tuple, list] = defaultdict(list)
    for r in razao:
        if r["id"] not in usados_razao:
            livres[(r["data"], r["v"])].append(r)
    extrato_sem_lancamento = []
    for m in restantes:
        fila = livres.get((m["data"], m["v"]))
        if fila:
            r = fila.pop(0)
            usados_razao.add(r["id"])
            casados.append((m["id"], r["id"], "data+valor"))
        else:
            extrato_sem_lancamento.append(m)
    sobras = [r for f in livres.values() for r in f]
    chaves_extrato = {(m["data"], m["v"]) for m in extrato}
    duplicidade = [r for r in sobras if (r["data"], r["v"]) in chaves_extrato]
    lancamento_sem_extrato = [r for r in sobras if (r["data"], r["v"]) not in chaves_extrato]
    res = {
        "periodo": periodo, "conta_banco": conta_banco,
        "extrato": len(extrato), "razao": len(razao), "casados": len(casados),
        "casados_por_marca": sum(1 for *_, t in casados if t == "marca"),
        "extrato_sem_lancamento": [dict(m) for m in extrato_sem_lancamento],
        "lancamento_sem_extrato": [dict(r) for r in lancamento_sem_extrato],
        "duplicidade_no_razao": [dict(r) for r in duplicidade],
        "divergentes": divergentes,
    }
    res["limpo"] = not (res["extrato_sem_lancamento"] or res["lancamento_sem_extrato"]
                        or res["duplicidade_no_razao"] or res["divergentes"])
    from storage.database import transacao
    with transacao(ctx.con):
        audit.registrar(ctx.con, ctx.nome, "conciliacao_extrato_razao", "conciliacao", f"{periodo}/{conta_banco}",
                        extrato=len(extrato), razao=len(razao), casados=len(casados),
                        sem_lancamento=len(extrato_sem_lancamento), sem_extrato=len(lancamento_sem_extrato),
                        duplicidades=len(duplicidade), divergentes=len(divergentes))
    return res
