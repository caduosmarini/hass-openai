"""Speech-to-text support for OpenAI and ElevenLabs."""

from collections.abc import AsyncIterable
import io
import logging
from typing import TYPE_CHECKING, override
import wave

import httpx
from openai import OpenAIError, omit

from homeassistant.components import stt
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_PROMPT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CHAT_MODEL,
    CONF_ELEVENLABS_API_KEY,
    CONF_PROVIDER,
    DEFAULT_ELEVENLABS_STT_MODEL,
    DEFAULT_STT_PROMPT,
    DOMAIN,
    PROVIDER_ELEVENLABS,
    RECOMMENDED_STT_MODEL,
)
from .elevenlabs import ElevenLabsClient
from .entity import OpenAIBaseLLMEntity

if TYPE_CHECKING:
    from . import OpenAIConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# https://elevenlabs.io/docs/overview/capabilities/speech-to-text
_ELEVENLABS_LANGUAGES = (
    "af am ar hy as ast az be bn bs bg my yue ca ceb ny hr cs da nl en et fil fi "
    "fr ff gl lg ka de el gu ha he hi hu is ig id ga it ja jv kea kn kk km ko ku "
    "ky lo lv ln lt luo lb mk ms ml mt zh mi mr mn ne nso no oc or ps fa pl pt "
    "pt-BR pt-PT pa ro ru sr sn sd si sk sl so es sw sv ta tg te th tr uk umb "
    "ur uz vi cy wo xh zu"
).split()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenAIConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up STT entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "stt":
            continue

        entity = (
            ElevenLabsSTTEntity(hass, config_entry, subentry)
            if subentry.data.get(CONF_PROVIDER) == PROVIDER_ELEVENLABS
            else OpenAISTTEntity(config_entry, subentry)
        )
        async_add_entities([entity], config_subentry_id=subentry.subentry_id)


class AudioStreamSTTEntity(stt.SpeechToTextEntity):
    """STT entity that accepts WAV or Ogg audio from Home Assistant."""

    @property
    @override
    def supported_formats(self) -> list[stt.AudioFormats]:
        """Return a list of supported formats."""
        return [stt.AudioFormats.WAV, stt.AudioFormats.OGG]

    @property
    @override
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        """Return a list of supported codecs."""
        return [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]

    @property
    @override
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        """Return a list of supported bit rates."""
        return [
            stt.AudioBitRates.BITRATE_8,
            stt.AudioBitRates.BITRATE_16,
            stt.AudioBitRates.BITRATE_24,
            stt.AudioBitRates.BITRATE_32,
        ]

    @property
    @override
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        """Return a list of supported sample rates."""
        return [
            stt.AudioSampleRates.SAMPLERATE_8000,
            stt.AudioSampleRates.SAMPLERATE_11000,
            stt.AudioSampleRates.SAMPLERATE_16000,
            stt.AudioSampleRates.SAMPLERATE_18900,
            stt.AudioSampleRates.SAMPLERATE_22000,
            stt.AudioSampleRates.SAMPLERATE_32000,
            stt.AudioSampleRates.SAMPLERATE_37800,
            stt.AudioSampleRates.SAMPLERATE_44100,
            stt.AudioSampleRates.SAMPLERATE_48000,
        ]

    @property
    @override
    def supported_channels(self) -> list[stt.AudioChannels]:
        """Return a list of supported channels."""
        return [stt.AudioChannels.CHANNEL_MONO, stt.AudioChannels.CHANNEL_STEREO]


async def _async_read_audio(stream: AsyncIterable[bytes]) -> bytes:
    """Collect the audio chunks received from Home Assistant."""
    audio = bytearray()
    async for chunk in stream:
        audio.extend(chunk)
    return bytes(audio)


def _add_wav_header(audio: bytes, metadata: stt.SpeechMetadata) -> bytes:
    """Wrap raw PCM frames in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(metadata.channel.value)
        wav.setsampwidth(metadata.bit_rate.value // 8)
        wav.setframerate(metadata.sample_rate.value)
        wav.writeframes(audio)
    return buffer.getvalue()


class OpenAISTTEntity(AudioStreamSTTEntity, OpenAIBaseLLMEntity):
    """OpenAI Speech to text entity."""

    @property
    @override
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        # https://developers.openai.com/api/docs/guides/speech-to-text#supported-languages
        # The model may also transcribe the audio in other
        # languages but with lower quality
        return [
            "af-ZA",  # Afrikaans
            "ar-SA",  # Arabic
            "hy-AM",  # Armenian
            "az-AZ",  # Azerbaijani
            "be-BY",  # Belarusian
            "bs-BA",  # Bosnian
            "bg-BG",  # Bulgarian
            "ca-ES",  # Catalan
            "zh-CN",  # Chinese (Mandarin)
            "hr-HR",  # Croatian
            "cs-CZ",  # Czech
            "da-DK",  # Danish
            "nl-NL",  # Dutch
            "en-US",  # English
            "et-EE",  # Estonian
            "fi-FI",  # Finnish
            "fr-FR",  # French
            "gl-ES",  # Galician
            "de-DE",  # German
            "el-GR",  # Greek
            "he-IL",  # Hebrew
            "hi-IN",  # Hindi
            "hu-HU",  # Hungarian
            "is-IS",  # Icelandic
            "id-ID",  # Indonesian
            "it-IT",  # Italian
            "ja-JP",  # Japanese
            "kn-IN",  # Kannada
            "kk-KZ",  # Kazakh
            "ko-KR",  # Korean
            "lv-LV",  # Latvian
            "lt-LT",  # Lithuanian
            "mk-MK",  # Macedonian
            "ms-MY",  # Malay
            "mr-IN",  # Marathi
            "mi-NZ",  # Maori
            "ne-NP",  # Nepali
            "no-NO",  # Norwegian
            "fa-IR",  # Persian
            "pl-PL",  # Polish
            "pt-PT",  # Portuguese
            "ro-RO",  # Romanian
            "ru-RU",  # Russian
            "sr-RS",  # Serbian
            "sk-SK",  # Slovak
            "sl-SI",  # Slovenian
            "es-ES",  # Spanish
            "sw-KE",  # Swahili
            "sv-SE",  # Swedish
            "fil-PH",  # Tagalog (Filipino)
            "ta-IN",  # Tamil
            "th-TH",  # Thai
            "tr-TR",  # Turkish
            "uk-UA",  # Ukrainian
            "ur-PK",  # Urdu
            "vi-VN",  # Vietnamese
            "cy-GB",  # Welsh
        ]

    @override
    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Process an audio stream to STT service."""
        audio_data = await _async_read_audio(stream)
        if metadata.format == stt.AudioFormats.WAV:
            audio_data = _add_wav_header(audio_data, metadata)

        options = self.subentry.data
        client = self.entry.runtime_data
        model = options.get(CONF_CHAT_MODEL, RECOMMENDED_STT_MODEL)
        language = metadata.language.split("-")[0]
        supports_language_list = model == "gpt-transcribe"
        diarize = model == "gpt-4o-transcribe-diarize"
        prompt = omit if diarize else options.get(CONF_PROMPT, DEFAULT_STT_PROMPT)

        try:
            response = await client.audio.transcriptions.create(
                model=model,
                file=(f"a.{metadata.format.value}", audio_data),
                response_format="json",
                language=omit if supports_language_list else language,
                languages=(
                    [language] if supports_language_list and len(language) == 2 else omit
                ),
                prompt=prompt,
                chunking_strategy="auto" if diarize else omit,
            )
        except OpenAIError:
            _LOGGER.exception("Error during STT")
        else:
            if response.text:
                return stt.SpeechResult(
                    response.text,
                    stt.SpeechResultState.SUCCESS,
                )

        return stt.SpeechResult(None, stt.SpeechResultState.ERROR)


class ElevenLabsSTTEntity(AudioStreamSTTEntity):
    """ElevenLabs speech recognition entity."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, hass: HomeAssistant, entry: OpenAIConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the model and its ElevenLabs client."""
        key = entry.data.get(CONF_ELEVENLABS_API_KEY)
        self._client = ElevenLabsClient(hass, key) if key else None
        self._model = subentry.data.get(CONF_CHAT_MODEL, DEFAULT_ELEVENLABS_STT_MODEL)
        self._attr_available = self._client is not None
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="ElevenLabs",
            model=self._model,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    @override
    def supported_languages(self) -> list[str]:
        """Return the languages recognized by Scribe."""
        return _ELEVENLABS_LANGUAGES

    @override
    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Transcribe the incoming audio with ElevenLabs."""
        if self._client is None:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        audio = await _async_read_audio(stream)
        if not audio:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        if metadata.format == stt.AudioFormats.WAV and not (
            audio.startswith(b"RIFF") and audio[8:12] == b"WAVE"
        ):
            audio = _add_wav_header(audio, metadata)

        extension = metadata.format.value
        try:
            text = await self._client.transcribe(
                audio,
                filename=f"audio.{extension}",
                content_type=f"audio/{extension}",
                model_id=self._model,
                language_code=metadata.language,
            )
        except httpx.HTTPStatusError as exc:
            _LOGGER.warning(
                "ElevenLabs transcription failed (HTTP %s)", exc.response.status_code
            )
        except (httpx.HTTPError, ValueError):
            _LOGGER.warning("Could not transcribe audio with ElevenLabs")
        else:
            return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)

        return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
