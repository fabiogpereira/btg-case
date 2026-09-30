"""Perfil determinístico ativo (E-006).

`v1` = comportamento congelado de A–E (padrão). `v2` = melhorias de cobertura da variante F
(formatos de data adicionais). O perfil é escolhido pela variante no orchestrator e vale só durante o
processamento daquele documento (ContextVar), sem mudar assinaturas nem o comportamento das variantes antigas.
"""
from contextvars import ContextVar

DETERMINISTIC_PROFILE: ContextVar[str] = ContextVar("deterministic_profile", default="v1")


def is_v2() -> bool:
    return DETERMINISTIC_PROFILE.get() == "v2"
