"""Suíte de qualidade das citações: respostas honestas e respostas com erros típicos
(artigo inventado, número alterado, página errada, trecho atribuído à fonte errada)."""
import json

import pytest

from nb import citations as c
from nb.rag import Hit

F1 = Hit(1, "d1", "resolucao.pdf", 34, "Art. 118 A inscrição semestral em componentes curriculares será efeti vada "
         "atendendo: I - ao limite mínimo de 12 (doze) e máximo de 32 (trinta e dois) créditos, exceto para os "
         "estudantes dos dois últimos períodos do curso;", 0.9)
F2 = Hit(2, "d1", "resolucao.pdf", 36, "Art. 125 O trancamento de curso é a suspensão oficial das atividades acadêmicas "
         "do estudante. § 1º O limite máximo para trancamentos de curso é de 04 (quatro) períodos letivos regulares.", 0.8)
F3 = Hit(3, "d2", "base.md", None, "Art. 1510 Texto de outro artigo qualquer sobre assunto diverso do pedido.", 0.5)
HITS = [F1, F2, F3]


def claim(tipo="documentada", texto="Afirmação", fontes=("F1",), trecho=None):
    return c.Claim(tipo, texto, list(fontes), trecho)


def check(*claims):
    return c.verify(c.Parsed(True, "", claims=list(claims)), HITS)


def only(*claims):
    return check(*claims)[0]


def test_citacao_literal_correta_e_confirmada_e_a_pagina_vem_do_trecho_nao_do_modelo():
    r = only(claim(texto="O limite é de 12 a 32 créditos.", trecho="limite mínimo de 12 (doze) e máximo de 32 (trinta e dois) créditos"))
    assert r.status == "confirmada" and not r.notes
    assert (r.sources[0].document_name, r.sources[0].page_number, r.sources[0].label) == ("resolucao.pdf", 34, "F1")


def test_confirma_apesar_de_espacos_indevidos_do_pdf_acentos_e_pontuacao():
    assert only(claim(trecho="A inscrição semestral... será efetivada atendendo")).status == "confirmada"
    assert only(claim(trecho="a INSCRICAO semestral em componentes curriculares sera efetivada")).status == "confirmada"


@pytest.mark.parametrize("trecho", [
    "limite mínimo de 12 e máximo de 33 créditos por semestre letivo",   # número alterado
    "A inscrição semestral será livre para todos os estudantes do curso",  # conteúdo inventado
    "Art. 119 O ajuste de inscrição é o período do Calendário Acadêmico",  # artigo que não está no trecho
])
def test_citacao_alterada_ou_inventada_nao_e_confirmada(trecho):
    assert only(claim(trecho=trecho)).status == "nao_confirmada"


def test_trecho_curto_demais_nao_prova_nada():
    assert only(claim(trecho="de 12")).status == "nao_confirmada"
    assert only(claim(trecho="Art. 118")).status == "nao_confirmada"


def test_citacao_de_outro_trecho_e_apontada_com_a_fonte_correta():
    r = only(claim(fontes=("F1",), trecho="O limite máximo para trancamentos de curso é de 04 (quatro) períodos letivos"))
    assert r.status == "outro_trecho" and any("F2" in n for n in r.notes)


def test_reticencias_exigem_segmentos_em_ordem():
    ok = "Art. 125 O trancamento de curso é a suspensão oficial [...] é de 04 (quatro) períodos letivos regulares"
    assert only(claim(fontes=("F2",), trecho=ok)).status == "confirmada"
    fora_de_ordem = "é de 04 (quatro) períodos letivos regulares ... Art. 125 O trancamento de curso é a suspensão oficial"
    assert only(claim(fontes=("F2",), trecho=fora_de_ordem)).status == "nao_confirmada"


def test_marcador_inexistente_e_denunciado_e_nao_conta_como_fonte():
    r = only(claim(fontes=("F9",), trecho="limite mínimo de 12 (doze) e máximo de 32 créditos"))
    assert r.status == "sem_fonte" and any("F9" in n for n in r.notes) and r.sources == []


def test_documentada_sem_trecho_ou_sem_fonte_e_marcada_como_sem_fonte():
    assert only(claim(trecho=None)).status == "sem_fonte"
    assert only(claim(fontes=(), trecho="limite mínimo de 12 (doze) e máximo de 32")).status == "sem_fonte"


def test_inferencia_e_recomendacao_nao_ganham_selo_de_documentada_mesmo_com_citacao_valida():
    a = only(claim(tipo="Inferência", texto="Logo, o aluno pode pedir exceção.", trecho="qualquer coisa"))
    b = only(claim(tipo="RECOMENDAÇÃO", texto="Procure a coordenação."))
    assert (a.status, b.status) == ("inferencia", "recomendacao")


def test_tipo_desconhecido_nao_e_verificado():
    assert only(claim(tipo="fato", trecho="limite mínimo de 12 (doze) e máximo de 32")).status == "formato_invalido"


def test_alerta_para_pagina_artigo_e_numero_que_nao_estao_nos_trechos_citados():
    base = dict(trecho="limite mínimo de 12 (doze) e máximo de 32 (trinta e dois) créditos")
    assert not only(claim(texto="Conforme o Art. 118, p. 34, o limite é de 12 a 32 créditos.", **base)).notes
    r = only(claim(texto="Conforme o Art. 119, página 99, o limite é de 40 créditos e § 7.", **base))
    texto = " ".join(r.notes)
    assert "página 99" in texto and "Art. 119" in texto and "número 40" in texto and "§ 7" in texto
    assert r.status == "confirmada"  # alertas não reprovam a citação literal


def test_artigo_citado_nao_casa_por_prefixo_numerico():
    r = only(claim(tipo="inferencia", texto="Veja o Art. 151.", fontes=("F3",)))
    assert any("Art. 151" in n for n in r.notes)  # F3 só tem Art. 1510


def test_alertas_tambem_valem_para_inferencia_com_fonte():
    r = only(claim(tipo="inferencia", texto="Em 60 dias o estudante perde o vínculo.", fontes=("F2",)))
    assert any("número 60" in n for n in r.notes)


def test_parse_aceita_json_com_cerca_de_codigo_e_fontes_como_texto():
    raw = '```json\n{"evidencia_suficiente": true, "afirmacoes": [{"tipo":"documentada","texto":"X","fontes":"F1","trecho":"abc"}, {"texto":""}, 5]}\n```'
    p = c.parse_response(raw)
    assert p.ok and p.evidencia_suficiente is True and len(p.claims) == 1 and p.claims[0].fontes == ["F1"]


@pytest.mark.parametrize("raw", ["", "texto livre sem json", "[1,2]", '{"afirmacoes": "x"}', "{quebrado"])
def test_parse_de_formato_invalido_nao_verifica_nada(raw):
    p = c.parse_response(raw)
    assert not p.ok and "nenhuma citação foi verificada" in p.error


def test_parse_insuficiencia_divergencias_e_lacunas():
    p = c.parse_response(json.dumps({"evidencia_suficiente": False, "afirmacoes": [], "divergencias": ["A x B"], "lacunas": "Falta o Art. 7"}))
    assert p.ok and p.evidencia_suficiente is False and p.divergencias == ["A x B"] and p.lacunas == "Falta o Art. 7"
    assert c.parse_response('{"evidencia_suficiente": "sim", "afirmacoes": []}').evidencia_suficiente is None


def test_resumo_conta_confirmadas_problemas_e_sinaliza_quando_nenhuma_confirma():
    good = claim(trecho="limite mínimo de 12 (doze) e máximo de 32 (trinta e dois) créditos")
    bad = claim(trecho="texto totalmente inventado pelo modelo sem base nenhuma")
    parsed = c.Parsed(True, "", claims=[good, bad, claim(tipo="inferencia", texto="Logo.")])
    s = c.summarize(parsed, c.verify(parsed, HITS))
    assert (s["documentadas"], s["confirmadas"], s["problemas"], s["nenhuma_confirmada"]) == (2, 1, 1, False)
    parsed = c.Parsed(True, "", claims=[bad])
    assert c.summarize(parsed, c.verify(parsed, HITS))["nenhuma_confirmada"] is True


def test_registro_json_guarda_trechos_paginas_e_status_para_auditoria():
    parsed = c.Parsed(True, "", claims=[claim(trecho="limite mínimo de 12 (doze) e máximo de 32 (trinta e dois) créditos")], lacunas="x")
    data = json.loads(c.to_json(parsed, c.verify(parsed, HITS), HITS))
    assert data["checks"][0]["status"] == "confirmada" and data["checks"][0]["sources"][0]["page_number"] == 34
    assert [h["label"] for h in data["hits"]] == ["F1", "F2", "F3"] and data["hits"][0]["text"].startswith("Art. 118")
    assert data["summary"]["confirmadas"] == 1 and data["parsed"]["lacunas"] == "x"


def test_fold_e_estavel_para_ordinais_e_hifens():
    assert c.fold("Art. 2º - pré-requisito") == c.fold("art 2o PRE REQUISITO")
