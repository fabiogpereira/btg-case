"""Harness do criador independente do BT-002.

Uma única chamada à API da Anthropic, em contexto limpo:
- sem system prompt, sem ferramentas, sem arquivos anexados, sem histórico;
- a única entrada é o texto de PROMPT.txt (gravado byte a byte ao lado);
- a saída bruta é gravada sem edição em response_raw.txt; metadados em response_meta.json;
- os blocos <<<FILE: ...>>> são extraídos para output/ sem nenhuma alteração de conteúdo.
A chave vem do ambiente (.env do projeto) e nunca é impressa nem gravada.
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
MODEL = sys.argv[1] if len(sys.argv) > 1 else "claude-sonnet-5"
MAX_TOKENS = 64000


def load_env(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_env(Path(sys.argv[2]))
    prompt = (HERE / "PROMPT.txt").read_text(encoding="utf-8")
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(timeout=1800, max_retries=2,
                                 default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    request = {"model": MODEL, "max_tokens": MAX_TOKENS, "thinking": {"type": "adaptive"},
               "messages": [{"role": "user", "content": prompt}]}
    (HERE / "request.json").write_text(json.dumps(
        {**{k: v for k, v in request.items() if k != "messages"}, "system": None, "tools": None,
         "prompt_file": "PROMPT.txt", "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t0 = time.time()
    with client.messages.stream(**request) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if b.type == "text")
    (HERE / "response_raw.txt").write_text(text, encoding="utf-8")
    meta = {"id": msg.id, "requested_model": MODEL, "served_model": msg.model, "stop_reason": msg.stop_reason,
            "usage": {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens},
            "latency_s": round(time.time() - t0, 1),
            "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    (HERE / "response_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    out = HERE / "output"
    out.mkdir(exist_ok=True)
    files = re.findall(r"<<<FILE: ([^>\n]+)>>>\n(.*?)\n?<<<END FILE>>>", text, flags=re.S)
    for name, content in files:
        (out / Path(name.strip()).name).write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")
    print(json.dumps({**meta, "files": [n.strip() for n, _ in files]}, indent=2))


if __name__ == "__main__":
    main()
