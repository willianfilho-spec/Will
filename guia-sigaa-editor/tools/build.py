#!/usr/bin/env python3
"""Gera guia-sigaa-editor/index.html a partir de app.template.html + seed.json.

Uso: python3 build.py seed.json ../index.html
"""
import json, sys, os

here = os.path.dirname(os.path.abspath(__file__))
seed = open(sys.argv[1], encoding='utf-8').read().replace('</', '<\\/')
tpl = open(os.path.join(here, 'app.template.html'), encoding='utf-8').read()
open(sys.argv[2], 'w', encoding='utf-8').write(tpl.replace('/*__SEED__*/', seed))
print('ok', os.path.getsize(sys.argv[2]), 'bytes')
