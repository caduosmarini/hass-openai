"""HTTP client for ElevenLabs speech recognition and synthesis."""

from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

_API_ROOT = "https://api.elevenlabs.io/v1"
_AUDIO_TIMEOUT = 60.0


class ElevenLabsClient:
    """Use Home Assistant's HTTP client for ElevenLabs voice requests."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Keep the key separate from other provider credentials."""
        self._client = get_async_client(hass)
        self._headers = {"xi-api-key": api_key}

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        content_type: str,
        model_id: str,
        language_code: str | None = None,
    ) -> str:
        """Send one audio file to Scribe and return the transcript text."""
        data = {
            "model_id": model_id,
            "tag_audio_events": "false",
            "timestamps_granularity": "none",
        }
        if language_code:
            data["language_code"] = language_code.split("-")[0].lower()

        response = await self._client.post(
            f"{_API_ROOT}/speech-to-text",
            headers=self._headers,
            data=data,
            files={"file": (filename, audio, content_type)},
            follow_redirects=False,
            timeout=_AUDIO_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str):
            raise ValueError("ElevenLabs did not return a transcript")
        return text

    async def synthesize(
        self,
        text: str,
        *,
        model_id: str,
        voice_id: str,
        language_code: str | None = None,
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        """Generate speech for the requested model and voice."""
        data = {"text": text, "model_id": model_id}
        if language_code and model_id != "eleven_multilingual_v2":
            data["language_code"] = language_code.split("-")[0].lower()

        response = await self._client.post(
            f"{_API_ROOT}/text-to-speech/{quote(voice_id, safe='')}",
            headers=self._headers,
            params={"output_format": output_format},
            json=data,
            follow_redirects=False,
            timeout=_AUDIO_TIMEOUT,
        )
        response.raise_for_status()
        if not response.content:
            raise ValueError("ElevenLabs did not return synthesized speech")
        return response.content
