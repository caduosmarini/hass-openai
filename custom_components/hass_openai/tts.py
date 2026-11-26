"""Text-to-speech support for OpenAI and ElevenLabs."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, override

import httpx
from openai import OpenAIError, omit
from propcache.api import cached_property

from homeassistant.components.tts import (
    ATTR_PREFERRED_FORMAT,
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_PROMPT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CHAT_MODEL,
    CONF_ELEVENLABS_API_KEY,
    CONF_ELEVENLABS_VOICE_ID,
    CONF_PROVIDER,
    CONF_TTS_SPEED,
    DEFAULT_ELEVENLABS_TTS_MODEL,
    DOMAIN,
    PROVIDER_ELEVENLABS,
    RECOMMENDED_TTS_MODEL,
    RECOMMENDED_TTS_SPEED,
)
from .elevenlabs import ElevenLabsClient
from .entity import OpenAIBaseLLMEntity

if TYPE_CHECKING:
    from . import OpenAIConfigEntry


PARALLEL_UPDATES = 0

# https://developers.openai.com/api/docs/guides/text-to-speech#voice-options
_LEGACY_OPENAI_TTS_MODELS = {"tts-1", "tts-1-hd"}
_LEGACY_OPENAI_TTS_VOICES = {
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
}

# https://elevenlabs.io/docs/overview/models
_ELEVENLABS_MULTILINGUAL_LANGUAGES = (
    "en ja zh de hi fr ko pt pt-BR pt-PT it es id nl tr fil pl sv bg ro ar cs "
    "el fi hr ms sk da ta uk ru"
).split()
_ELEVENLABS_FLASH_LANGUAGES = [*_ELEVENLABS_MULTILINGUAL_LANGUAGES, "hu", "no", "vi"]
_ELEVENLABS_V3_LANGUAGES = (
    "af ar hy as ast az be bn bs bg my yue ca ceb ny hr cs da nl en et fil fi "
    "fr gl ka de el gu ha he hi hu is id ga it ja jv kn kk ky ko lv ln lt lb mk "
    "ms ml mt zh mi mr mn ne no oc or ps fa pl pt pt-BR pt-PT pa ro ru sr sd sk "
    "sl so es sw sv tg ta te th tr uk ur uz vi cy yo"
).split()
_ELEVENLABS_V4_LANGUAGES = (
    "af am ar hy as ast az be bn bs bg my yue ca ceb hr cs da nl en et fil fi "
    "fr ff gl ka de el gu ha he hi hu is id it ja jv kam kn kk ko ky lo lv ln "
    "lt lg lb mk ms ml mt zh mi mr mn ne no oc or ps fa pl pt pt-BR pt-PT pa ro "
    "ru sr sn sd sk sl so ckb es sw sv tg ta te th tr uk ur uz vi cy wo zu"
).split()
_ELEVENLABS_MODEL_LANGUAGES = {
    "eleven_flash_v2": ["en"],
    "eleven_turbo_v2": ["en"],
    "eleven_english_v1": ["en"],
    "eleven_multilingual_v1": "en de pl es it fr pt pt-BR pt-PT hi".split(),
    "eleven_multilingual_v2": _ELEVENLABS_MULTILINGUAL_LANGUAGES,
    "eleven_v3": _ELEVENLABS_V3_LANGUAGES,
    "eleven_v4": _ELEVENLABS_V4_LANGUAGES,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenAIConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TTS entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "tts":
            continue

        entity = (
            ElevenLabsTTSEntity(hass, config_entry, subentry)
            if subentry.data.get(CONF_PROVIDER) == PROVIDER_ELEVENLABS
            else OpenAITTSEntity(config_entry, subentry)
        )
        async_add_entities([entity], config_subentry_id=subentry.subentry_id)


class OpenAITTSEntity(TextToSpeechEntity, OpenAIBaseLLMEntity):
    """OpenAI TTS entity."""

    _attr_supported_options = [ATTR_VOICE, ATTR_PREFERRED_FORMAT]
    # https://platform.openai.com/docs/guides/text-to-speech#supported-languages
    # The model may also generate the audio in different
    # languages but with lower quality
    _attr_supported_languages = [
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
    # Unused, but required by base class.
    # The models detect the input language automatically.
    _attr_default_language = "en-US"

    # https://platform.openai.com/docs/guides/text-to-speech#voice-options
    _supported_voices = [
        Voice(voice.lower(), voice)
        for voice in (
            "Marin",
            "Cedar",
            "Alloy",
            "Ash",
            "Ballad",
            "Coral",
            "Echo",
            "Fable",
            "Nova",
            "Onyx",
            "Sage",
            "Shimmer",
            "Verse",
        )
    ]
    _legacy_supported_voices = [
        voice
        for voice in _supported_voices
        if voice.voice_id in _LEGACY_OPENAI_TTS_VOICES
    ]
    _legacy_unsupported_voice_ids = (
        {voice.voice_id for voice in _supported_voices} - _LEGACY_OPENAI_TTS_VOICES
    )

    _supported_formats = ["mp3", "opus", "aac", "flac", "wav", "pcm"]

    _attr_has_entity_name = False

    def __init__(self, entry: OpenAIConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        super().__init__(entry, subentry)
        self._model = subentry.data.get(CONF_CHAT_MODEL) or RECOMMENDED_TTS_MODEL
        self._attr_device_info["model"] = self._model
        self._attr_name = subentry.title

    @callback
    @override
    def async_get_supported_voices(self, language: str) -> list[Voice]:
        """Return a list of supported voices for a language."""
        if self._model in _LEGACY_OPENAI_TTS_MODELS:
            return self._legacy_supported_voices
        return self._supported_voices

    @cached_property
    @override
    def default_options(self) -> Mapping[str, Any]:
        """Return a mapping with the default options."""
        voices = self.async_get_supported_voices(self._attr_default_language)
        return {
            ATTR_VOICE: voices[0].voice_id,
            ATTR_PREFERRED_FORMAT: "mp3",
        }

    @override
    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Load tts audio file from the engine."""

        options = {**self.subentry.data, **options}
        client = self.entry.runtime_data
        model = options.get(CONF_CHAT_MODEL) or self._model
        legacy_model = model in _LEGACY_OPENAI_TTS_MODELS
        voice = options[ATTR_VOICE]
        if (
            legacy_model
            and isinstance(voice, str)
            and voice in self._legacy_unsupported_voice_ids
        ):
            # A pipeline can still store a voice selected with a previous model.
            voice = self._legacy_supported_voices[0].voice_id
        prompt = options.get(CONF_PROMPT)

        response_format = options[ATTR_PREFERRED_FORMAT]
        if response_format in ("ogg", "oga"):
            codec: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "opus"
        elif response_format == "raw":
            response_format = codec = "pcm"
        elif response_format not in self._supported_formats:
            response_format = self.default_options[ATTR_PREFERRED_FORMAT]
            codec = response_format
        else:
            codec = response_format

        try:
            async with client.audio.speech.with_streaming_response.create(
                model=model,
                voice=voice,
                input=message,
                instructions=str(prompt) if prompt and not legacy_model else omit,
                speed=options.get(CONF_TTS_SPEED, RECOMMENDED_TTS_SPEED),
                response_format=codec,
            ) as response:
                response_data = bytearray()
                async for chunk in response.iter_bytes():
                    response_data.extend(chunk)
        except OpenAIError as exc:
            raise HomeAssistantError(exc) from exc

        return response_format, bytes(response_data)


class ElevenLabsTTSEntity(TextToSpeechEntity):
    """ElevenLabs text-to-speech entity."""

    _attr_default_language = "en"
    _attr_has_entity_name = False
    _attr_supported_options = [ATTR_VOICE]

    def __init__(
        self, hass: HomeAssistant, entry: OpenAIConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the model, voice, and ElevenLabs client."""
        key = entry.data.get(CONF_ELEVENLABS_API_KEY)
        self._client = ElevenLabsClient(hass, key) if key else None
        self._model = subentry.data.get(CONF_CHAT_MODEL, DEFAULT_ELEVENLABS_TTS_MODEL)
        self._voice_id = subentry.data.get(CONF_ELEVENLABS_VOICE_ID)
        if self._voice_id:
            self._attr_default_options = {ATTR_VOICE: self._voice_id}
        self._attr_available = self._client is not None and bool(self._voice_id)
        self._attr_name = subentry.title
        self._attr_supported_languages = _ELEVENLABS_MODEL_LANGUAGES.get(
            self._model, _ELEVENLABS_FLASH_LANGUAGES
        )
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="ElevenLabs",
            model=self._model,
            entry_type=DeviceEntryType.SERVICE,
        )

    @callback
    @override
    def async_get_supported_voices(self, language: str) -> list[Voice]:
        """Return the voice configured for this entity."""
        return [Voice(self._voice_id, self._voice_id)] if self._voice_id else []

    @override
    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Generate MP3 audio using the ElevenLabs model and voice."""
        if self._client is None:
            raise HomeAssistantError("Configure the ElevenLabs API key before using TTS")
        if not (voice_id := options.get(ATTR_VOICE) or self._voice_id):
            raise HomeAssistantError("Configure an ElevenLabs voice before using TTS")

        try:
            audio = await self._client.synthesize(
                message,
                model_id=self._model,
                voice_id=voice_id,
                language_code=language,
            )
        except httpx.HTTPStatusError as exc:
            raise HomeAssistantError(
                f"ElevenLabs speech synthesis failed (HTTP {exc.response.status_code})"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HomeAssistantError("Could not generate speech with ElevenLabs") from exc

        return "mp3", audio
