import time
from typing import Any

from loguru import logger

from backend.app.config.config import load_config

# === НАСТРОЙКИ OLLAMA (ДЛЯ GLM-OCR) ===
OLLAMA_MODEL = "glm-ocr"
try:
    OLLAMA_HOST = load_config().ocr.ollama_host
except Exception:
    OLLAMA_HOST = "http://localhost:11434"

_client: Any = None


def _get_ollama_client():
    global _client
    if _client is None:
        from ollama import AsyncClient

        _client = AsyncClient(host=OLLAMA_HOST)
    return _client


async def process_text(file_bytes: bytes) -> str:
    start_time = time.perf_counter()
    try:
        client = _get_ollama_client()

        # Вызываем генерацию напрямую (библиотека сама переведет байты картинки в нужный формат)
        response = await client.generate(
            model=OLLAMA_MODEL,
            prompt=(
                "Extract the text from this image and return it strictly as plain text. "
                "Do not include any explanations or markdown code blocks, just the text."
            ),
            images=[file_bytes],
            stream=False,
            options={"temperature": 0.0, "top_p": 0.1},
            keep_alive="0m",
        )

        text = response.get("response", "").strip()

        # Очищаем от возможных Markdown-оберток, если нейросеть их добавит
        if text.startswith("```html"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]
        end_time = time.perf_counter()

        logger.info(
            f"Время выполнения извлечения текста {OLLAMA_MODEL}: {end_time - start_time:.2f}"
        )

        return text.strip()

    except Exception as e:
        logger.error(f"Произошла ошибка при обращении к Ollama: {str(e)}")
        return ""


async def unload_model():
    """Принудительно выгружает модель из видеопамяти."""
    try:
        client = _get_ollama_client()
        logger.info(f"Очистка видеопамяти от модели {OLLAMA_MODEL}...")
        # Пустой запрос с keep_alive=0 заставляет Ollama немедленно выгрузить модель
        await client.generate(model=OLLAMA_MODEL, keep_alive=0)
    except Exception as e:
        logger.error(f"Ошибка при выгрузке модели: {e}")
