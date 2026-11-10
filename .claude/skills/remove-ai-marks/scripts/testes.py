#!/usr/bin/env python3
"""Testes dos scripts da skill. Rode com: python3 testes.py"""

import base64
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpar_unicode as lu  # noqa: E402
import pontuador_estatistico as pe  # noqa: E402
import servico  # noqa: E402


class LimpezaUnicode(unittest.TestCase):
    def test_remove_invisiveis_e_preserva_visiveis(self):
        sujo = "﻿Ação​ rápida⁠, “com aspas” — e­ traço‮. Fim hoje"
        limpo, rel = lu.limpar(sujo)
        self.assertEqual(limpo, "Ação rápida, “com aspas” — e traço.\nFim hoje")
        self.assertEqual(rel["residuo"], 0)
        self.assertEqual(rel["total"], 7)
        self.assertEqual(rel["por_categoria"]["largura_zero"], 3)

    def test_texto_limpo_fica_intacto(self):
        texto = "Art. 5º, § 2º — não há o que alterar.\n\tLinha com tab e acentuação: ãõçé.\r\n"
        limpo, rel = lu.limpar(texto)
        self.assertEqual(limpo, texto)
        self.assertFalse(rel["alterado"])
        self.assertFalse(lu.inspecionar(texto)["suspeito"])

    def test_preserva_emoji_composto_e_bandeira(self):
        texto = "família 👨‍👩‍👧, coração ❤️, tecla 1️⃣, 🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"
        self.assertEqual(lu.limpar(texto)[0], texto)

    def test_remove_tags_e_seletores_soltos(self):
        texto = "ol\U000e0041\U000e0042á a️ b︁"
        self.assertEqual(lu.limpar(texto)[0], "olá a b")

    def test_nbsp_so_com_opcao(self):
        self.assertEqual(lu.limpar("R$ 10")[0], "R$ 10")
        self.assertEqual(lu.limpar("R$ 10", nbsp=True)[0], "R$ 10")

    def test_homoglifos_so_em_palavra_mista(self):
        limpo, rel = lu.limpar("pаypal e Москва", homoglifos=True)  # "а" cirílico em paypal
        self.assertEqual(limpo, "paypal e Москва")
        self.assertEqual(rel["homoglifos_trocados"], 1)

    def test_posicao_relatada(self):
        rel = lu.inspecionar("linha um\nab​c")
        self.assertEqual(rel["caracteres"][0]["exemplos"][0], {"linha": 2, "coluna": 3})


FORMULAICO = " ".join([
    "É importante destacar que a gestão desempenha um papel fundamental no cenário atual.",
    "Além disso, a tecnologia é crucial para resultados robustos, eficientes e abrangentes.",
    "Nesse sentido, vale ressaltar que a inovação é essencial para todas as organizações.",
    "Em suma, não é apenas uma ferramenta, mas uma jornada de transformação contínua.",
] * 12)

VARIADO = (
    "Choveu a noite inteira. De manhã, o barracão do seu Antenor tinha um palmo de água, e as sacas de "
    "farinha que ele guardava para a feira de sábado estavam perdidas; ninguém ali tinha seguro, claro.\n\n"
    "Fui até lá com o Zeca. Ele levou a bomba emprestada do cunhado, eu levei café. Trabalhamos calados "
    "por quase duas horas, até que a filha do Antenor apareceu perguntando se alguém tinha visto o gato.\n\n"
    "Não tínhamos. O bicho surgiu depois, seco, em cima do armário, olhando para nós como quem cobra aluguel. "
    "Rimos pela primeira vez no dia.\n\n"
    "A prefeitura prometeu limpar o bueiro em março. Estamos em agosto. Quando liguei de novo, a atendente "
    "pediu o número do protocolo, que eu perdi junto com a paciência, e desligou antes que eu achasse outro "
    "papel onde anotar. Vou lá amanhã, pessoalmente, com as fotos impressas e a conta do prejuízo somada à mão."
)


class Pontuador(unittest.TestCase):
    def test_formulaico_pontua_mais_que_variado(self):
        f, v = pe.pontuar(FORMULAICO), pe.pontuar(VARIADO)
        self.assertTrue(f["ok"] and v["ok"])
        self.assertGreater(f["indice_padronizacao"], v["indice_padronizacao"] + 30)
        self.assertGreater(f["metricas"]["cliches_por_mil"], 20)
        self.assertEqual(v["cliches_encontrados"], {})

    def test_texto_curto_marcado_como_nao_confiavel(self):
        r = pe.pontuar("Uma frase só. Outra frase curta.")
        self.assertFalse(r["confiavel"])
        self.assertIn("instável", r["aviso"])

    def test_vazio(self):
        self.assertFalse(pe.pontuar("  \n ")["ok"])

    def test_abreviacao_nao_quebra_frase(self):
        self.assertEqual(len(pe._frases("Conforme o art. 5º da Lei, o Dr. Silva recorreu. Perdeu.")), 2)


class Servico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = servico.criar_servidor("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def pedir(self, rota, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + rota, data=dados, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read())

    @staticmethod
    def b64(texto):
        return base64.b64encode(texto.encode("utf-8")).decode()

    def test_health_e_capacidades(self):
        self.assertEqual(self.pedir("/health")[1]["ok"], True)
        cap = self.pedir("/capabilities")[1]
        self.assertTrue(cap["scorers"]["stylometry"])
        self.assertFalse(cap["layer_b_rewrite"])

    def test_inspect_e_clean(self):
        corpo = {"file": self.b64("a​b"), "name": "n.txt"}
        _, insp = self.pedir("/inspect", corpo)
        self.assertTrue(insp["suspicious"])
        status, limpo = self.pedir("/clean", {**corpo, "options": {"detect_after": True}})
        self.assertEqual(status, 200)
        self.assertEqual(base64.b64decode(limpo["cleaned"]).decode(), "ab")
        self.assertFalse(limpo["report"]["layer_b"]["applied"])
        self.assertIn("after", limpo["report"]["text_detectors"])

    def test_detect(self):
        _, r = self.pedir("/detect", {"file": self.b64(FORMULAICO), "name": "t.txt"})
        self.assertEqual(r["detections"][0]["detector"], "stylometry")
        self.assertGreater(r["detections"][0]["resultado"]["indice_padronizacao"], 40)

    def test_erros(self):
        self.assertEqual(self.pedir("/clean", {"file": self.b64("x"), "name": "f.pdf"})[0], 400)
        self.assertEqual(self.pedir("/clean", {"file": "###", "name": "f.txt"})[0], 400)
        self.assertEqual(self.pedir("/clean", {"file": self.b64("x"), "name": "f.txt",
                                               "options": {"strategy": "paraphrase@0.8"}})[0], 400)
        self.assertEqual(self.pedir("/nada", {})[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=1)
