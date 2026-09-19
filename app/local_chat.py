"""Local-only conversational inference. No keys, paid fallback, or executable model output."""
import json
import urllib.request

ENDPOINT = "http://127.0.0.1:8081/v1/chat/completions"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Local model redirects are disabled")


def chat(message, history=(), timeout=90):
    messages = [{"role":"system", "content":
        "You are Cell, a conversational assistant. Answer in the user's language. "
        "You can explain, draft text and write code as text. You cannot browse, read attachments, "
        "execute code, edit files or delegate in this local chat mode. Never claim you performed "
        "these actions. Be honest about uncertainty. Answer directly and concisely. /no_think"}]
    # UTF-8 byte bound is conservative for this byte-fallback tokenizer and 4096 context.
    if len(message.encode("utf-8")) > 1800:
        raise ValueError("로컬 시험 모델은 한 번에 UTF-8 1,800바이트까지 받습니다. 질문을 나누어 주세요.")
    remaining = 2200 - len(message.encode("utf-8"))
    recent = []
    for entry in reversed(list(history)[-12:]):
        if entry.get("role") not in {"user", "assistant"}:
            continue
        content = str(entry["content"])
        size = len(content.encode("utf-8"))
        if size > remaining:
            break
        recent.append({"role": entry["role"], "content": content})
        remaining -= size
    messages.extend(reversed(recent))
    messages.append({"role":"user","content":message})
    body = dict(model="cell-local",messages=messages,stream=False,max_tokens=512,
                temperature=0.3,chat_template_kwargs={"enable_thinking":False})
    request = urllib.request.Request(ENDPOINT,data=json.dumps(body).encode(),
                                    headers={"Content-Type":"application/json"})
    # Ignore environment HTTP proxies: local prompts must stay on loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect)
    try:
        with opener.open(request,timeout=timeout) as response:
            data=response.read(262145)
        if len(data)>262144:
            raise ValueError("Local model response exceeds limit")
        result=json.loads(data)
        choice=result["choices"][0]
        text=choice["message"].get("content")
        if not isinstance(text,str) or not text.strip():
            raise ValueError("Local model returned no answer")
        if choice.get("finish_reason")=="length":
            text += "\n\n[응답 길이 한도에 도달했습니다. 이어서 설명해 달라고 요청할 수 있습니다.]"
        return text
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"로컬 모델이 요청을 처리하지 못했습니다 (HTTP {error.code}). 질문을 줄이거나 모델 서버 로그를 확인하세요.") from error
    except urllib.error.URLError as error:
        raise RuntimeError("로컬 모델에 연결하지 못했습니다. 127.0.0.1:8081에서 llama-server를 시작하세요. 외부 유료 API로 전환하지 않습니다.") from error
