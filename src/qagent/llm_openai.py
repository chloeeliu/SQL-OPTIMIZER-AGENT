# llm openai.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List
from openai import OpenAI

@dataclass
class LLMConfig:
    model: str = "gpt-5"  
    max_output_tokens: int = 1200

class OpenAIResponsesLLM:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.client = OpenAI()

    def responses_create(self, input_messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        resp = self.client.responses.create(
            model=self.cfg.model,
            input=input_messages,
            tools=tools,
            max_output_tokens=self.cfg.max_output_tokens,
            parallel_tool_calls=False,
        )
        try:
            return resp.model_dump()
        except Exception:
            return resp
