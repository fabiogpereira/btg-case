"""Configuração do LLM a partir de variáveis de ambiente / .env. Segredos nunca são impressos nem gravados."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Parser mínimo de .env (KEY=VALUE). Não sobrescreve variáveis já definidas no ambiente."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    effort: str
    max_tokens: int
    fallbacks: str          # "off" (padrão; E-003 avalia configuração fixa) | "default" (fallback de recusa do servidor)
    timeout_s: float

    def public(self) -> dict:
        """Versão segura para audit/manifest (sem segredos)."""
        return {"provider": self.provider, "model": self.model, "effort": self.effort,
                "max_tokens": self.max_tokens, "fallbacks": self.fallbacks}


def llm_config_from_env() -> LLMConfig:
    load_dotenv()
    return LLMConfig(
        provider=os.environ.get("LLM_PROVIDER", "anthropic"),
        model=os.environ.get("LLM_MODEL", "claude-opus-5"),
        effort=os.environ.get("LLM_EFFORT", "medium"),
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "8000")),
        fallbacks=os.environ.get("LLM_FALLBACKS", "off"),
        timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "120")),
    )
