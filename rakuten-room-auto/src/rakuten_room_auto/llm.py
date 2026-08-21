from __future__ import annotations

from dataclasses import dataclass

from .config import LLMConfig


class DescriptionError(RuntimeError):
    pass


@dataclass
class DescriptionGenerator:
    config: LLMConfig

    def generate(self, product_url: str) -> str:
        if not self.config.enabled:
            raise DescriptionError("LLM description generation is disabled.")
        if self.config.provider != "openai":
            raise DescriptionError(f"Unsupported LLM provider: {self.config.provider}")
        if not self.config.model:
            raise DescriptionError("llm.model is required when LLM generation is enabled.")

        from openai import OpenAI

        prompt = (
            "楽天ROOMの商品紹介文を日本語で作成してください。"
            "誇大表現を避け、自然で購入者目線の短文にしてください。"
            f"{self.config.max_chars}文字以内。商品URL: {product_url}"
        )
        client = OpenAI()
        try:
            response = client.responses.create(model=self.config.model, input=prompt)
            text = getattr(response, "output_text", "") or ""
        except AttributeError:
            completion = client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
            )
            text = completion.choices[0].message.content or ""
        text = " ".join(text.split())
        if not text:
            raise DescriptionError("LLM returned an empty description.")
        return text[: self.config.max_chars]
