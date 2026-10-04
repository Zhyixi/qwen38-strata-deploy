"""Smoke-test Strata through LangChain's OpenAI-compatible client."""

import os

from langchain_openai import ChatOpenAI


base_url = os.getenv("STRATA_BASE_URL", "http://127.0.0.1:8080/v1")
api_key = os.getenv("STRATA_API_KEY", "none")
model = os.getenv("STRATA_MODEL", "qwen3.8-flash-next-iq2_xs")

llm = ChatOpenAI(
    model=model,
    base_url=base_url,
    api_key=api_key,
    temperature=0,
    timeout=300,
    max_retries=1,
)

prompt = "請用繁體中文回答一句：LangChain 已成功連上 Strata。"

if os.getenv("STRATA_TEST_STREAM") == "1":
    chunks = []
    for chunk in llm.stream(prompt):
        if chunk.content:
            print(chunk.content, end="", flush=True)
            chunks.append(str(chunk.content))
    print()
    content = "".join(chunks)
else:
    response = llm.invoke(prompt)
    content = str(response.content)
    print(content)
    if response.usage_metadata:
        print("usage:", response.usage_metadata)

if not content.strip():
    raise RuntimeError("Strata returned an empty response through LangChain")

print("PASS: LangChain ChatOpenAI -> Strata")
