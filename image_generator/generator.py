"""NanoBanana2 (Gemini 3.1 Flash Image Preview) を使った画像生成.

単一画像生成とバッチ（複数同時）画像生成をサポート。
asyncio.gather で並行リクエストを実現し、セマフォでレート制限を管理する。
"""

import asyncio
import base64
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from google import genai
from google.genai import types

from image_generator.config import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    GEMINI_API_KEY,
    MAX_CONCURRENT_REQUESTS,
    RETRY_BASE_DELAY,
    RETRY_MAX_ATTEMPTS,
)

logger = logging.getLogger(__name__)


@dataclass
class ImageRequest:
    """画像生成リクエストの定義."""

    prompt: str
    filename: str | None = None
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    # 追加の指示（スタイル指定など）
    style_prefix: str = ""

    @property
    def full_prompt(self) -> str:
        if self.style_prefix:
            return f"{self.style_prefix}. {self.prompt}"
        return self.prompt


@dataclass
class ImageResult:
    """画像生成結果."""

    request: ImageRequest
    success: bool
    filepath: str | None = None
    error: str | None = None
    duration_sec: float = 0.0


class ImageGenerator:
    """単一画像の生成を担当するクラス."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        output_dir: str = DEFAULT_OUTPUT_DIR,
    ):
        resolved_key = api_key or GEMINI_API_KEY
        if not resolved_key:
            raise ValueError(
                "GEMINI_API_KEY が設定されていません。"
                "環境変数 GEMINI_API_KEY を設定するか、api_key 引数で指定してください。"
            )

        self.client = genai.Client(api_key=resolved_key)
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, request: ImageRequest) -> ImageResult:
        """同期的に1枚の画像を生成して保存する."""
        start = time.time()
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=request.full_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=request.aspect_ratio,
                    ),
                ),
            )

            filepath = self._save_image(response, request)
            duration = time.time() - start
            logger.info("生成完了: %s (%.1f秒)", filepath, duration)
            return ImageResult(
                request=request, success=True,
                filepath=str(filepath), duration_sec=duration,
            )

        except Exception as e:
            duration = time.time() - start
            logger.error("生成失敗: %s - %s", request.prompt[:50], e)
            return ImageResult(
                request=request, success=False,
                error=str(e), duration_sec=duration,
            )

    def _save_image(self, response, request: ImageRequest) -> Path:
        """レスポンスから画像を取り出してファイルに保存する."""
        for part in response.parts:
            if part.inline_data:
                image = part.as_image()
                filename = request.filename or self._generate_filename(request.prompt)
                filepath = self.output_dir / filename
                image.save(str(filepath))
                return filepath

        raise RuntimeError("レスポンスに画像データが含まれていません。")

    @staticmethod
    def _generate_filename(prompt: str) -> str:
        """プロンプトからファイル名を生成する."""
        safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in prompt[:40])
        safe = safe.strip().replace(" ", "_")
        timestamp = int(time.time() * 1000)
        return f"{safe}_{timestamp}.png"


class BatchImageGenerator:
    """複数画像の並行生成を管理するクラス.

    asyncio.gather + セマフォ で同時リクエスト数を制御しつつ、
    指数バックオフ付きリトライで信頼性を確保する。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
    ):
        resolved_key = api_key or GEMINI_API_KEY
        if not resolved_key:
            raise ValueError(
                "GEMINI_API_KEY が設定されていません。"
                "環境変数 GEMINI_API_KEY を設定するか、api_key 引数で指定してください。"
            )

        self.api_key = resolved_key
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max_concurrent

    def generate_batch(self, requests: list[ImageRequest]) -> list[ImageResult]:
        """複数の画像生成リクエストを並行実行する (同期ラッパー)."""
        return asyncio.run(self._generate_batch_async(requests))

    async def _generate_batch_async(
        self, requests: list[ImageRequest],
    ) -> list[ImageResult]:
        """非同期バッチ生成の本体."""
        client = genai.Client(api_key=self.api_key)
        semaphore = asyncio.Semaphore(self.max_concurrent)

        tasks = [
            self._generate_one(client, req, semaphore, idx + 1, len(requests))
            for idx, req in enumerate(requests)
        ]

        results = await asyncio.gather(*tasks)
        return list(results)

    async def _generate_one(
        self,
        client: genai.Client,
        request: ImageRequest,
        semaphore: asyncio.Semaphore,
        index: int,
        total: int,
    ) -> ImageResult:
        """セマフォ制御＋リトライ付きで1枚を非同期生成する."""
        async with semaphore:
            for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                start = time.time()
                try:
                    logger.info(
                        "[%d/%d] 生成中 (試行 %d): %s",
                        index, total, attempt, request.prompt[:60],
                    )

                    response = await client.aio.models.generate_content(
                        model=self.model,
                        contents=request.full_prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"],
                            image_config=types.ImageConfig(
                                aspect_ratio=request.aspect_ratio,
                            ),
                        ),
                    )

                    filepath = self._save_image(response, request)
                    duration = time.time() - start
                    logger.info(
                        "[%d/%d] 完了: %s (%.1f秒)", index, total, filepath, duration,
                    )
                    return ImageResult(
                        request=request, success=True,
                        filepath=str(filepath), duration_sec=duration,
                    )

                except Exception as e:
                    duration = time.time() - start
                    if attempt < RETRY_MAX_ATTEMPTS:
                        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                        logger.warning(
                            "[%d/%d] 試行 %d 失敗: %s (%.1f秒後にリトライ)",
                            index, total, attempt, e, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[%d/%d] 全試行失敗: %s - %s",
                            index, total, request.prompt[:50], e,
                        )
                        return ImageResult(
                            request=request, success=False,
                            error=str(e), duration_sec=duration,
                        )

        # ここには到達しないはずだが安全のため
        return ImageResult(request=request, success=False, error="不明なエラー")

    def _save_image(self, response, request: ImageRequest) -> Path:
        """レスポンスから画像データを保存する."""
        for part in response.parts:
            if part.inline_data:
                image = part.as_image()
                filename = request.filename or self._generate_filename(request.prompt)
                filepath = self.output_dir / filename
                image.save(str(filepath))
                return filepath

        raise RuntimeError("レスポンスに画像データが含まれていません。")

    @staticmethod
    def _generate_filename(prompt: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in prompt[:40])
        safe = safe.strip().replace(" ", "_")
        timestamp = int(time.time() * 1000)
        return f"{safe}_{timestamp}.png"
