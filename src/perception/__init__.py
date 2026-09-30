"""Camada de percepção (E-008): converte documento sem camada de texto em texto. Não interpreta nada.

Plugada no pipeline congelado pelo hook `process_document(text_fallback=...)`; tudo depois do texto é o mesmo
pipeline (extração, semântica, validação, roteamento, auditoria).
"""
