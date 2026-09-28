"""
title: Manipulador PDF DIOAC
author: DIOAC
version: 4.1.1
description: >
    Localiza uma ocorrência exata de texto em um PDF e a substitui, preservando
    fonte incorporada, tamanho, cor e posição. Gera backup automático do
    original, nunca sobrescreve o arquivo de origem, e recusa a edição sempre
    que não conseguir garantir a preservação de tipografia/layout.
requirements: pymupdf, fonttools, pydantic
"""

import hashlib
import io
import os
import re
import shutil
from datetime import datetime

import fitz  # PyMuPDF
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import cmap_format_4
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Exceção interna usada para interromper a operação em qualquer ponto em que
# a preservação de tipografia/layout não possa ser garantida. Isso implementa
# a regra de segurança: "se a preservação não puder ser garantida, a
# ferramenta deve recusar a alteração".
# --------------------------------------------------------------------------
class EdicaoRecusada(Exception):
    pass


def _sha256(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_tounicode_cmap(cmap_text: str) -> dict:
    """Faz o parse de um CMap ToUnicode (bfchar/bfrange) e retorna {code: unicode}."""
    code2uni = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap_text, re.S):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            code_hex, dst_hex = m.groups()
            if len(dst_hex) <= 4:  # ignora ligaduras/multi-codepoint
                code2uni[int(code_hex, 16)] = int(dst_hex, 16)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap_text, re.S):
        for m in re.finditer(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
        ):
            lo_hex, hi_hex, dst_hex = m.groups()
            if len(dst_hex) > 4:
                continue
            lo, hi, dst = int(lo_hex, 16), int(hi_hex, 16), int(dst_hex, 16)
            for i, code in enumerate(range(lo, hi + 1)):
                code2uni[code] = dst + i
    return code2uni


def _get_uni2gid(doc: "fitz.Document", font_xref: int) -> dict:
    """
    Reconstrói o mapeamento Unicode -> GID de uma fonte composta (Type0 /
    Identity-H), a partir do /ToUnicode e do /CIDToGIDMap do PDF.

    Isso é necessário porque, ao gerar o PDF, o processo de subsetting remove
    a tabela 'cmap' da fonte incorporada (ela não é usada em tempo de
    renderização por fontes Identity-H) — então `fitz.Font(fontbuffer=...)`
    não sabe resolver caractere -> glifo, e inserir texto pelo nome de fonte
    interno (ex.: "/TT3") falha ou, pior, insere caixas vazias em silêncio.
    """
    obj_text = doc.xref_object(font_xref)
    m = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", obj_text)
    if not m:
        raise EdicaoRecusada(
            "fonte incorporada sem tabela /ToUnicode; não é possível "
            "validar com segurança quais caracteres o glifo suporta"
        )
    tounicode_xref = int(m.group(1))
    cmap_text = doc.xref_stream(tounicode_xref).decode("latin-1")
    code2uni = _parse_tounicode_cmap(cmap_text)
    if not code2uni:
        raise EdicaoRecusada("não foi possível interpretar o /ToUnicode da fonte")

    m2 = re.search(r"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", obj_text)
    if not m2:
        raise EdicaoRecusada("fonte Type0 sem /DescendantFonts válido")
    desc_xref = int(m2.group(1))
    desc_text = doc.xref_object(desc_xref)

    code2gid = None
    m3 = re.search(r"/CIDToGIDMap\s+(\d+)\s+0\s+R", desc_text)
    if m3:
        raw = doc.xref_stream(int(m3.group(1)))
        code2gid = {
            cid: (raw[2 * cid] << 8 | raw[2 * cid + 1]) for cid in range(len(raw) // 2)
        }
    # se não houver /CIDToGIDMap, o padrão é /Identity: GID == CID

    uni2gid = {}
    for code, uni in code2uni.items():
        gid = code2gid[code] if code2gid is not None else code
        uni2gid[uni] = gid
    return uni2gid


def _glyph_has_outline(tt: TTFont, glyph_name: str) -> bool:
    """
    Confirma que o glifo realmente tem contorno desenhado no buffer da fonte
    incorporada — e não apenas uma entrada "vazia" deixada pelo subsetting.

    Esse é o problema mais perigoso de todos: um caractere pode ter uma
    entrada válida de Unicode -> GID (passo anterior) e mesmo assim ter sido
    esvaziado pelo subsetting, porque não era usado em nenhum lugar do PDF
    original. Nesse caso a inserção "funciona" sem erro, mas o caractere
    simplesmente não aparece na página — uma corrupção silenciosa.
    """
    if "glyf" in tt:
        glyf = tt["glyf"]
        if glyph_name not in glyf:
            return False
        g = glyf[glyph_name]
        if g.isComposite():
            return len(g.components) > 0
        return getattr(g, "numberOfContours", 0) != 0
    if "CFF " in tt:
        # fontes CFF/Type1C: presença no charstrings é o melhor sinal disponível
        cff = tt["CFF "].cff
        top = cff[cff.fontNames[0]]
        return glyph_name in top.CharStrings
    # sem 'glyf' nem 'CFF ': não há como confirmar contorno -> trate como ausente
    return False


def _repair_font_buffer(font_bytes: bytes, uni2gid: dict) -> bytes:
    """Reconstrói uma tabela 'cmap' válida (Unicode -> glifo) no buffer extraído."""
    tt = TTFont(io.BytesIO(font_bytes))
    glyph_order = tt.getGlyphOrder()
    mapping = {}
    for uni, gid in uni2gid.items():
        if 0 <= gid < len(glyph_order):
            mapping[uni] = glyph_order[gid]
    sub4 = cmap_format_4(4)
    sub4.platformID, sub4.platEncID, sub4.language = 3, 1, 0
    sub4.cmap = mapping
    cmap_table = newTable("cmap")
    cmap_table.tableVersion = 0
    cmap_table.tables = [sub4]
    tt["cmap"] = cmap_table
    out = io.BytesIO()
    tt.save(out)
    return out.getvalue()


def _find_ocorrencia(doc, texto_original, ocorrencia, pagina=None):
    """
    Varre o(s) página(s) caractere a caractere (rawdict) e localiza a
    N-ésima ocorrência exata de `texto_original` dentro de um único span
    (mesma fonte/tamanho/cor). Ocorrências que cruzam spans com tipografias
    diferentes são ignoradas — não é seguro presumir qual tipografia usar.
    """
    paginas = [pagina - 1] if pagina else range(len(doc))
    achados = 0
    for pno in paginas:
        page = doc[pno]
        rd = page.get_text("rawdict")
        for b in rd["blocks"]:
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    chars = s.get("chars", [])
                    texto_span = "".join(c["c"] for c in chars)
                    start = 0
                    while True:
                        idx = texto_span.find(texto_original, start)
                        if idx == -1:
                            break
                        achados += 1
                        if achados == ocorrencia:
                            matched = chars[idx: idx + len(texto_original)]
                            x0 = min(c["bbox"][0] for c in matched)
                            y0 = min(c["bbox"][1] for c in matched)
                            x1 = max(c["bbox"][2] for c in matched)
                            y1 = max(c["bbox"][3] for c in matched)
                            return {
                                "pagina": pno,
                                "rect": fitz.Rect(x0, y0, x1, y1),
                                "origem": matched[0]["origin"],
                                "fonte": s["font"],
                                "tamanho": s["size"],
                                "cor": s["color"],
                            }
                        start = idx + 1
    return None


def _cor_int_para_rgb(cor_int: int):
    r = ((cor_int >> 16) & 255) / 255.0
    g = ((cor_int >> 8) & 255) / 255.0
    b = (cor_int & 255) / 255.0
    return (r, g, b)


def _detectar_cor_fundo(page, rect: "fitz.Rect"):
    """Amostra um pixel logo acima do texto para estimar a cor de fundo local."""
    try:
        amostra = fitz.Rect(rect.x0, max(0, rect.y0 - 3), rect.x0 + 2, rect.y0 - 1)
        pix = page.get_pixmap(clip=amostra, dpi=72)
        if pix.n >= 3 and pix.width > 0 and pix.height > 0:
            px = pix.pixel(0, 0)
            return (px[0] / 255.0, px[1] / 255.0, px[2] / 255.0)
    except Exception:
        pass
    return (1, 1, 1)  # branco como padrão seguro


class Tools:
    class Valves(BaseModel):
        BACKUP_DIR: str = Field(
            default=os.path.join(
                os.path.expanduser("~"), "Desktop", "DIOAC_PDF", "BACKUP"
            ),
            description="Pasta onde o PDF original é copiado antes de qualquer edição.",
        )
        OUTPUT_DIR: str = Field(
            default=os.path.join(
                os.path.expanduser("~"), "Desktop", "DIOAC_PDF", "EDITADOS"
            ),
            description="Pasta onde o novo PDF editado é gravado.",
        )
        TOLERANCIA_LARGURA: float = Field(
            default=1.03,
            description="Fator de tolerância (>=1.0) para o texto novo caber no espaço do texto original.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def editar_pdf(
        self,
        caminho_pdf: str,
        texto_original: str,
        texto_novo: str,
        ocorrencia: int = 1,
        pagina: int = None,
    ) -> str:
        """
        Localiza uma ocorrência exata de texto_original em um PDF e a
        substitui por texto_novo, preservando fonte, tamanho, cor e posição.
        Gera backup do arquivo original antes de qualquer alteração e grava
        o resultado em um novo arquivo, sem jamais sobrescrever o original.
        Recusa a operação sempre que não puder garantir a preservação da
        tipografia (fonte sem caractere necessário, texto que não cabe no
        espaço original, etc).

        Reproduza literalmente os parâmetros recebidos do usuário — não
        corrija, resuma, reformule ou reinterprete texto_original/texto_novo.

        :param caminho_pdf: Caminho completo do arquivo PDF a ser editado.
        :param texto_original: Texto exato a localizar (sensível a maiúsculas/minúsculas).
        :param texto_novo: Texto que substituirá texto_original.
        :param ocorrencia: Número da ocorrência a substituir, se o texto repetir (padrão 1).
        :param pagina: Página específica (1-based) onde procurar; se omitido, procura no documento inteiro.
        :return: Relatório estruturado do resultado (STATUS=SUCESSO|RECUSADO|ERRO, ...).
        """
        campos = {
            "ORIGINAL": caminho_pdf,
            "TEXTO_ORIGINAL": texto_original,
            "TEXTO_NOVO": texto_novo,
            "OCORRENCIA": str(ocorrencia),
        }

        def _falha(status, motivo, extras=None):
            linhas = [f"STATUS={status}"]
            for k, v in campos.items():
                linhas.append(f"{k}={v}")
            if extras:
                for k, v in extras.items():
                    linhas.append(f"{k}={v}")
            linhas.append(f"MOTIVO={motivo}")
            linhas.append("VALIDACAO=REPROVADA" if status == "ERRO" else "VALIDACAO=RECUSADA")
            return "\n".join(linhas)

        if not os.path.isfile(caminho_pdf):
            return _falha("ERRO", "arquivo PDF não encontrado")

        os.makedirs(self.valves.BACKUP_DIR, exist_ok=True)
        os.makedirs(self.valves.OUTPUT_DIR, exist_ok=True)

        hash_original_antes = _sha256(caminho_pdf)
        stem = os.path.splitext(os.path.basename(caminho_pdf))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho_backup = os.path.join(self.valves.BACKUP_DIR, f"{stem}_{timestamp}.pdf")
        try:
            shutil.copy2(caminho_pdf, caminho_backup)
        except Exception as e:
            return _falha("ERRO", f"falha ao gerar backup: {e}")

        try:
            doc = fitz.open(caminho_pdf)
        except Exception as e:
            return _falha("ERRO", f"não foi possível abrir o PDF: {e}", {"BACKUP": caminho_backup})

        try:
            achado = _find_ocorrencia(doc, texto_original, ocorrencia, pagina)
            if achado is None:
                raise EdicaoRecusada(
                    f"ocorrência #{ocorrencia} de \"{texto_original}\" não localizada "
                    "(dentro de um único trecho com tipografia uniforme)"
                )

            page = doc[achado["pagina"]]
            rect = achado["rect"]
            fontsize = achado["tamanho"]
            cor_rgb = _cor_int_para_rgb(achado["cor"])
            fonte_original_nome = achado["fonte"]

            xref_fonte = None
            for f in page.get_fonts(full=True):
                xref, ext, ftype, basefont, name, encoding = f[:6]
                nome_sem_subset = basefont.split("+", 1)[-1]
                if nome_sem_subset == fonte_original_nome or basefont == fonte_original_nome:
                    xref_fonte = xref
                    break
            if xref_fonte is None:
                raise EdicaoRecusada(
                    f"fonte \"{fonte_original_nome}\" não localizada nos recursos da página"
                )

            basefont, ext, ftype, raw_buf = doc.extract_font(xref_fonte)

            if ftype == "Type0":
                uni2gid = _get_uni2gid(doc, xref_fonte)
                buffer_para_inserir = _repair_font_buffer(raw_buf, uni2gid)
                tt = TTFont(io.BytesIO(raw_buf))
                glyph_order = tt.getGlyphOrder()

                def gid_de(ch):
                    return uni2gid.get(ord(ch))

            else:
                # fonte simples (Type1/TrueType não composta): o cmap embutido
                # normalmente já é utilizável diretamente
                buffer_para_inserir = raw_buf
                tt = TTFont(io.BytesIO(raw_buf))
                glyph_order = tt.getGlyphOrder()
                font_simples = fitz.Font(fontbuffer=raw_buf)

                def gid_de(ch):
                    return font_simples.has_glyph(ord(ch)) or None

            ausentes = []
            for ch in dict.fromkeys(texto_novo):  # únicos, preserva ordem
                if ch in ("\n", "\r"):
                    ausentes.append(repr(ch) + " (quebra de linha não suportada)")
                    continue
                if ch == " ":
                    continue  # espaço é legitimamente um glifo sem contorno
                gid = gid_de(ch)
                if gid is None or gid == 0:
                    ausentes.append(repr(ch))
                    continue
                nome_glifo = glyph_order[gid] if gid < len(glyph_order) else None
                if not nome_glifo or not _glyph_has_outline(tt, nome_glifo):
                    ausentes.append(f"{ch!r} (sem desenho na fonte incorporada)")

            if ausentes:
                raise EdicaoRecusada(
                    "a fonte incorporada não contém todos os caracteres do "
                    "texto novo com garantia de renderização correta: "
                    + ", ".join(ausentes)
                )

            font_para_medir = fitz.Font(fontbuffer=buffer_para_inserir)
            largura_nova = font_para_medir.text_length(texto_novo, fontsize=fontsize)
            largura_disponivel = rect.width * self.valves.TOLERANCIA_LARGURA
            if largura_nova > largura_disponivel:
                raise EdicaoRecusada(
                    f"texto novo ({largura_nova:.1f}pt) não cabe no espaço do "
                    f"texto original ({rect.width:.1f}pt, tolerância "
                    f"{self.valves.TOLERANCIA_LARGURA:.0%})"
                )

            cor_fundo = _detectar_cor_fundo(page, rect)
            page.add_redact_annot(rect, fill=cor_fundo)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)

            alias = "DIOAC_" + hashlib.md5(fonte_original_nome.encode()).hexdigest()[:8]
            page.insert_font(fontname=alias, fontbuffer=buffer_para_inserir)
            page.insert_text(
                achado["origem"], texto_novo, fontname=alias, fontsize=fontsize, color=cor_rgb
            )

            nome_saida = f"{stem}_{timestamp}_editado.pdf"
            caminho_saida = os.path.join(self.valves.OUTPUT_DIR, nome_saida)
            doc.save(caminho_saida, garbage=4, deflate=True)
            doc.close()

            # ---- validação pós-gravação ----
            hash_original_depois = _sha256(caminho_pdf)
            if hash_original_depois != hash_original_antes:
                return _falha(
                    "ERRO",
                    "o arquivo original foi alterado durante a operação (hash divergente)",
                    {"BACKUP": caminho_backup},
                )

            doc_validacao = fitz.open(caminho_saida)
            page_validacao = doc_validacao[achado["pagina"]]
            texto_lido = page_validacao.get_textbox(rect + (-1, -1, largura_nova + 5, 1))
            doc_validacao.close()
            aprovado = texto_novo in texto_lido

            linhas = [
                "STATUS=SUCESSO",
                f"ORIGINAL={caminho_pdf}",
                f"BACKUP={caminho_backup}",
                f"EDITADO={caminho_saida}",
                f"PAGINA={achado['pagina'] + 1}",
                f"OCORRENCIA={ocorrencia}",
                f"TEXTO_ORIGINAL={texto_original}",
                f"TEXTO_NOVO={texto_novo}",
                f"FONTE_ORIGINAL={fonte_original_nome}",
                f"TAMANHO={fontsize}",
                f"VALIDACAO={'APROVADA' if aprovado else 'REVISAR_MANUALMENTE'}",
            ]
            return "\n".join(linhas)

        except EdicaoRecusada as e:
            try:
                doc.close()
            except Exception:
                pass
            return _falha("RECUSADO", str(e), {"BACKUP": caminho_backup})
        except Exception as e:
            try:
                doc.close()
            except Exception:
                pass
            return _falha("ERRO", f"falha inesperada: {e}", {"BACKUP": caminho_backup})
