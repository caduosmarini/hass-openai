"""Config flow for OpenAI Conversation integration.

Adapted for the Hass OpenAI custom integration.
"""

from abc import abstractmethod
from collections.abc import Mapping
import json
import logging
from typing import Any, override

import httpx
import openai
import probatio

from homeassistant import data_entry_flow
from homeassistant.components.zone import ENTITY_ID_HOME
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LLM_HASS_API,
    CONF_NAME,
    CONF_PROMPT,
    EntityStateAttribute,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm
from homeassistant.helpers.field_visibility import FieldCondition
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.typing import VolDictType

from . import create_client, get_base_url
from .const import (
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_CODE_INTERPRETER,
    CONF_ELEVENLABS_API_KEY,
    CONF_ELEVENLABS_VOICE_ID,
    CONF_IMAGE_MODEL,
    CONF_MAX_TOKENS,
    CONF_PRO_MODE,
    CONF_PROVIDER,
    CONF_REASONING_EFFORT,
    CONF_REASONING_SUMMARY,
    CONF_RECOMMENDED,
    CONF_SERVICE_TIER,
    CONF_STORE_RESPONSES,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    CONF_TTS_SPEED,
    CONF_VERBOSITY,
    CONF_WEB_SEARCH,
    CONF_WEB_SEARCH_CITY,
    CONF_WEB_SEARCH_CONTEXT_SIZE,
    CONF_WEB_SEARCH_COUNTRY,
    CONF_WEB_SEARCH_INLINE_CITATIONS,
    CONF_WEB_SEARCH_REGION,
    CONF_WEB_SEARCH_TIMEZONE,
    CONF_WEB_SEARCH_USER_LOCATION,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_BASE_URL,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_ELEVENLABS_STT_MODEL,
    DEFAULT_ELEVENLABS_TTS_MODEL,
    DEFAULT_ENTRY_TITLE,
    DEFAULT_EVALUATION_NAME,
    DEFAULT_STT_NAME,
    DEFAULT_STT_PROMPT,
    DEFAULT_TTS_NAME,
    DOMAIN,
    PROVIDER_ELEVENLABS,
    PROVIDER_OPENAI,
    RECOMMENDED_AI_TASK_OPTIONS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CODE_INTERPRETER,
    RECOMMENDED_CONVERSATION_OPTIONS,
    RECOMMENDED_DECISION_MODEL,
    RECOMMENDED_EVALUATION_OPTIONS,
    RECOMMENDED_IMAGE_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_PRO_MODE,
    RECOMMENDED_REASONING_EFFORT,
    RECOMMENDED_REASONING_SUMMARY,
    RECOMMENDED_SERVICE_TIER,
    RECOMMENDED_STORE_RESPONSES,
    RECOMMENDED_STT_MODEL,
    RECOMMENDED_STT_OPTIONS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
    RECOMMENDED_TTS_MODEL,
    RECOMMENDED_TTS_OPTIONS,
    RECOMMENDED_TTS_SPEED,
    RECOMMENDED_VERBOSITY,
    RECOMMENDED_WEB_SEARCH,
    RECOMMENDED_WEB_SEARCH_CONTEXT_SIZE,
    RECOMMENDED_WEB_SEARCH_INLINE_CITATIONS,
    RECOMMENDED_WEB_SEARCH_USER_LOCATION,
    SUPPORTED_ULTRAFAST_MODELS,
    UNSUPPORTED_CODE_INTERPRETER_MODELS,
    UNSUPPORTED_FLEX_SERVICE_TIERS_MODELS,
    UNSUPPORTED_IMAGE_MODELS,
    UNSUPPORTED_MODELS,
    UNSUPPORTED_PRIORITY_SERVICE_TIERS_MODELS,
    UNSUPPORTED_WEB_SEARCH_MODELS,
)

_LOGGER = logging.getLogger(__name__)
CONF_REMOVE_ELEVENLABS_KEY = "remove_elevenlabs_key"
CONF_CUSTOM_AUDIO_MODEL = "custom_audio_model"
OTHER_AUDIO_MODEL = "__other__"

STEP_REAUTH_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(probatio.Secret(CONF_API_KEY)): str,
    }
)
STEP_USER_DATA_SCHEMA = STEP_REAUTH_DATA_SCHEMA.extend(
    {
        probatio.Optional(CONF_BASE_URL): str,
        probatio.Optional(probatio.Secret(CONF_ELEVENLABS_API_KEY)): str,
    }
)
STEP_RECONFIGURE_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Optional(probatio.Secret(CONF_API_KEY)): str,
        probatio.Optional(CONF_BASE_URL): str,
        probatio.Optional(probatio.Secret(CONF_ELEVENLABS_API_KEY)): str,
    }
)


def normalize_base_url(value: str) -> str:
    """Validate and normalize an alternative API base URL."""
    url = httpx.URL(value)
    if (
        url.scheme not in ("http", "https")
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise httpx.InvalidURL("Expected an HTTP or HTTPS API base URL")
    return str(url).rstrip("/")


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    client = create_client(hass, data)
    await client.models.list(timeout=10.0)


class OpenAIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenAI Conversation."""

    VERSION = 2
    MINOR_VERSION = 8

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        return await self._async_step_api_key(user_input, "user")

    async def _async_step_api_key(
        self, user_input: dict[str, Any] | None, step_id: str
    ) -> ConfigFlowResult:
        """Handle the API connection form."""
        errors: dict[str, str] = {}
        entry = None
        schema = STEP_USER_DATA_SCHEMA
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            schema = STEP_REAUTH_DATA_SCHEMA
        elif self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            schema = STEP_RECONFIGURE_DATA_SCHEMA
            if entry.data.get(CONF_ELEVENLABS_API_KEY):
                schema = schema.extend(
                    {probatio.Optional(CONF_REMOVE_ELEVENLABS_KEY): bool}
                )

        saved_data = entry.data if entry is not None else {}
        suggested_url = (user_input or {}).get(
            CONF_BASE_URL, saved_data.get(CONF_BASE_URL, "")
        )

        if user_input is not None:
            data = dict(saved_data)
            if api_key := user_input.get(CONF_API_KEY, "").strip():
                data[CONF_API_KEY] = api_key
            if self.source != SOURCE_REAUTH:
                try:
                    if base_url := suggested_url.strip():
                        data[CONF_BASE_URL] = normalize_base_url(base_url)
                    else:
                        data.pop(CONF_BASE_URL, None)
                except httpx.InvalidURL:
                    errors[CONF_BASE_URL] = "invalid_base_url"

                if user_input.get(CONF_REMOVE_ELEVENLABS_KEY):
                    data.pop(CONF_ELEVENLABS_API_KEY, None)
                elif elevenlabs_key := user_input.get(CONF_ELEVENLABS_API_KEY, "").strip():
                    data[CONF_ELEVENLABS_API_KEY] = elevenlabs_key

            if not api_key and (
                self.source != SOURCE_RECONFIGURE
                or not data.get(CONF_API_KEY)
                or get_base_url(data) != get_base_url(saved_data)
            ):
                errors[CONF_API_KEY] = "api_key_required"

            if not errors:
                self._abort_duplicate_connection(data)
                if error := await self._async_validate_connection(data):
                    errors["base"] = error

            if not errors:
                self._abort_duplicate_connection(data)
                if entry is not None:
                    if entry.update_listeners:
                        return self.async_update_and_abort(entry, data=data)
                    return self.async_update_reload_and_abort(entry, data=data)
                return self.async_create_entry(
                    title=DEFAULT_ENTRY_TITLE,
                    data=data,
                    subentries=[
                        {
                            "subentry_type": "conversation",
                            "data": RECOMMENDED_CONVERSATION_OPTIONS,
                            "title": DEFAULT_CONVERSATION_NAME,
                            "unique_id": None,
                        },
                        {
                            "subentry_type": "ai_task_data",
                            "data": RECOMMENDED_AI_TASK_OPTIONS,
                            "title": DEFAULT_AI_TASK_NAME,
                            "unique_id": None,
                        },
                        {
                            "subentry_type": "ai_task_evaluate",
                            "data": RECOMMENDED_EVALUATION_OPTIONS,
                            "title": DEFAULT_EVALUATION_NAME,
                            "unique_id": None,
                        },
                        {
                            "subentry_type": "stt",
                            "data": RECOMMENDED_STT_OPTIONS,
                            "title": DEFAULT_STT_NAME,
                            "unique_id": None,
                        },
                        {
                            "subentry_type": "tts",
                            "data": RECOMMENDED_TTS_OPTIONS,
                            "title": DEFAULT_TTS_NAME,
                            "unique_id": None,
                        },
                    ],
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_BASE_URL: suggested_url}
            ),
            errors=errors,
            description_placeholders={
                "instructions_url": "https://www.home-assistant.io/integrations/openai_conversation/#prerequisites",
            },
        )

    def _abort_duplicate_connection(self, data: dict[str, Any]) -> None:
        """Abort if the endpoint and API key are already configured."""
        for entry in self._async_current_entries(include_ignore=False):
            if (
                entry.entry_id != self.context.get("entry_id")
                and entry.data.get(CONF_API_KEY) == data[CONF_API_KEY]
                and get_base_url(entry.data) == get_base_url(data)
            ):
                raise data_entry_flow.AbortFlow("already_configured")

    async def _async_validate_connection(self, data: dict[str, Any]) -> str | None:
        """Return the form error for a failed connection."""
        try:
            await validate_input(self.hass, data)
        except openai.APIConnectionError:
            return "cannot_connect"
        except openai.AuthenticationError:
            return "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            return "unknown"
        return None

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        return await self._async_step_api_key(user_input, "reauth_confirm")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the API connection."""
        return await self._async_step_api_key(user_input, "reconfigure")

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {
            "conversation": OpenAISubentryFlowHandler,
            "ai_task_data": OpenAISubentryFlowHandler,
            "ai_task_evaluate": OpenAISubentryEvaluationFlowHandler,
            "stt": OpenAISubentrySTTFlowHandler,
            "tts": OpenAISubentryTTSFlowHandler,
        }


class OpenAISubentryFlowHandler(ConfigSubentryFlow):
    """Flow for managing OpenAI subentries."""

    options: dict[str, Any]

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == "user"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a subentry."""
        if self._subentry_type == "ai_task_data":
            self.options = RECOMMENDED_AI_TASK_OPTIONS.copy()
        else:
            self.options = RECOMMENDED_CONVERSATION_OPTIONS.copy()
        return await self.async_step_init()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a subentry."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_init()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage initial options."""
        # abort if entry is not loaded
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        options = self.options
        errors: dict[str, str] = {}

        hass_apis: list[SelectOptionDict] = [
            SelectOptionDict(
                label=api.name,
                value=api.id,
            )
            for api in llm.async_get_apis(self.hass)
        ]
        if suggested_llm_apis := options.get(CONF_LLM_HASS_API):
            if isinstance(suggested_llm_apis, str):
                suggested_llm_apis = [suggested_llm_apis]
            valid_apis = {api.id for api in llm.async_get_apis(self.hass)}
            options[CONF_LLM_HASS_API] = [
                api for api in suggested_llm_apis if api in valid_apis
            ]

        step_schema: VolDictType = {}

        if self._is_new:
            if self._subentry_type == "ai_task_data":
                default_name = DEFAULT_AI_TASK_NAME
            else:
                default_name = DEFAULT_CONVERSATION_NAME
            step_schema[probatio.Required(CONF_NAME, default=default_name)] = str

        if self._subentry_type == "conversation":
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_PROMPT,
                        description={
                            "suggested_value": options.get(
                                CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT
                            )
                        },
                    ): TemplateSelector(),
                    probatio.Optional(CONF_LLM_HASS_API): SelectSelector(
                        SelectSelectorConfig(
                            options=hass_apis,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            )

        step_schema[
            probatio.Required(
                CONF_RECOMMENDED, default=options.get(CONF_RECOMMENDED, False)
            )
        ] = bool

        not_recommended: FieldCondition = {
            "field": CONF_RECOMMENDED,
            "value": False,
        }
        step_schema.update(
            {
                data_entry_flow.Optional(
                    CONF_CHAT_MODEL,
                    default=RECOMMENDED_CHAT_MODEL,
                    visible=not_recommended,
                ): str,
                data_entry_flow.Optional(
                    CONF_MAX_TOKENS,
                    default=RECOMMENDED_MAX_TOKENS,
                    visible=not_recommended,
                ): int,
                data_entry_flow.Optional(
                    CONF_TOP_P,
                    default=RECOMMENDED_TOP_P,
                    visible=not_recommended,
                ): NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05)),
                data_entry_flow.Optional(
                    CONF_TEMPERATURE,
                    default=RECOMMENDED_TEMPERATURE,
                    visible=not_recommended,
                ): NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.05)),
                data_entry_flow.Optional(
                    CONF_STORE_RESPONSES,
                    default=RECOMMENDED_STORE_RESPONSES,
                    visible=not_recommended,
                ): bool,
            }
        )

        if user_input is not None:
            if user_input.get(CONF_LLM_HASS_API) is None:
                user_input.pop(CONF_LLM_HASS_API, None)

            if user_input[CONF_RECOMMENDED]:
                if self._is_new:
                    return self.async_create_entry(
                        title=user_input.pop(CONF_NAME),
                        data=user_input,
                    )
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    data=user_input,
                )

            if user_input.get(CONF_CHAT_MODEL) in UNSUPPORTED_MODELS:
                errors[CONF_CHAT_MODEL] = "model_not_supported"

            options.update(user_input)
            if CONF_LLM_HASS_API in options and CONF_LLM_HASS_API not in user_input:
                options.pop(CONF_LLM_HASS_API)
            if not errors:
                return await self.async_step_model()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(step_schema), options
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage model-specific options."""
        options = self.options
        errors: dict[str, str] = {}

        step_schema: VolDictType = {}

        model = options[CONF_CHAT_MODEL]

        if not model.startswith(tuple(UNSUPPORTED_CODE_INTERPRETER_MODELS)):
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_CODE_INTERPRETER,
                        default=RECOMMENDED_CODE_INTERPRETER,
                    ): bool,
                }
            )
        elif CONF_CODE_INTERPRETER in options:
            options.pop(CONF_CODE_INTERPRETER)

        if reasoning_options := self._get_reasoning_options(model):
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_REASONING_EFFORT,
                        default=RECOMMENDED_REASONING_EFFORT,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=reasoning_options,
                            translation_key=CONF_REASONING_EFFORT,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        elif CONF_REASONING_EFFORT in options:
            options.pop(CONF_REASONING_EFFORT)

        if model.startswith(("gpt-5.6", "gpt-6")):
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_PRO_MODE,
                        default=RECOMMENDED_PRO_MODE,
                    ): bool,
                }
            )
        elif CONF_PRO_MODE in options:
            options.pop(CONF_PRO_MODE)

        if model.startswith(("gpt-5", "gpt-6")):
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_VERBOSITY,
                        default=RECOMMENDED_VERBOSITY,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["low", "medium", "high"],
                            translation_key=CONF_VERBOSITY,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        elif CONF_VERBOSITY in options:
            options.pop(CONF_VERBOSITY)

        if model.startswith(("o", "gpt-5", "gpt-6")):
            reasoning_summary_options = ["off", "auto", "concise", "detailed"]
            if model.startswith("o"):
                reasoning_summary_options.remove("concise")
            stored_summary = options.get(
                CONF_REASONING_SUMMARY, RECOMMENDED_REASONING_SUMMARY
            )
            if stored_summary not in reasoning_summary_options:
                stored_summary = RECOMMENDED_REASONING_SUMMARY
                options[CONF_REASONING_SUMMARY] = stored_summary
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_REASONING_SUMMARY,
                        default=stored_summary,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=reasoning_summary_options,
                            translation_key=CONF_REASONING_SUMMARY,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        elif CONF_REASONING_SUMMARY in options:
            options.pop(CONF_REASONING_SUMMARY)

        service_tiers = self._get_service_tiers(model)
        if service_tiers != ["auto", "default"]:
            step_schema[
                probatio.Optional(
                    CONF_SERVICE_TIER,
                    default=RECOMMENDED_SERVICE_TIER,
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=service_tiers,
                    translation_key=CONF_SERVICE_TIER,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            options.pop(CONF_SERVICE_TIER, None)
        if options.get(CONF_SERVICE_TIER) not in service_tiers:
            options.pop(CONF_SERVICE_TIER, None)

        if not model.startswith(tuple(UNSUPPORTED_WEB_SEARCH_MODELS)):
            step_schema.update(
                {
                    probatio.Optional(
                        CONF_WEB_SEARCH,
                        default=RECOMMENDED_WEB_SEARCH,
                    ): bool,
                    probatio.Optional(
                        CONF_WEB_SEARCH_CONTEXT_SIZE,
                        default=RECOMMENDED_WEB_SEARCH_CONTEXT_SIZE,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["low", "medium", "high"],
                            translation_key=CONF_WEB_SEARCH_CONTEXT_SIZE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    probatio.Optional(
                        CONF_WEB_SEARCH_USER_LOCATION,
                        default=RECOMMENDED_WEB_SEARCH_USER_LOCATION,
                    ): bool,
                    probatio.Optional(
                        CONF_WEB_SEARCH_INLINE_CITATIONS,
                        default=RECOMMENDED_WEB_SEARCH_INLINE_CITATIONS,
                    ): bool,
                }
            )
        elif CONF_WEB_SEARCH in options:
            options = {
                k: v
                for k, v in options.items()
                if k
                not in (
                    CONF_WEB_SEARCH,
                    CONF_WEB_SEARCH_CONTEXT_SIZE,
                    CONF_WEB_SEARCH_USER_LOCATION,
                    CONF_WEB_SEARCH_CITY,
                    CONF_WEB_SEARCH_REGION,
                    CONF_WEB_SEARCH_COUNTRY,
                    CONF_WEB_SEARCH_TIMEZONE,
                    CONF_WEB_SEARCH_INLINE_CITATIONS,
                )
            }

        if self._subentry_type == "ai_task_data" and not model.startswith(
            tuple(UNSUPPORTED_IMAGE_MODELS)
        ):
            step_schema[
                probatio.Optional(CONF_IMAGE_MODEL, default=RECOMMENDED_IMAGE_MODEL)
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        "gpt-image-2.5-sunburst",
                        "gpt-image-2.5-flare",
                        "gpt-image-2",
                        "gpt-image-1.5",
                        "gpt-image-1",
                        "gpt-image-1-mini",
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        if user_input is not None:
            if user_input.get(CONF_WEB_SEARCH):
                if user_input.get(CONF_REASONING_EFFORT) == "minimal":
                    errors[CONF_WEB_SEARCH] = "web_search_minimal_reasoning"
                if user_input.get(CONF_WEB_SEARCH_USER_LOCATION) and not errors:
                    user_input.update(await self._get_location_data())
                else:
                    options.pop(CONF_WEB_SEARCH_CITY, None)
                    options.pop(CONF_WEB_SEARCH_REGION, None)
                    options.pop(CONF_WEB_SEARCH_COUNTRY, None)
                    options.pop(CONF_WEB_SEARCH_TIMEZONE, None)
            if (
                user_input.get(CONF_CODE_INTERPRETER)
                and user_input.get(CONF_REASONING_EFFORT) == "minimal"
            ):
                errors[CONF_CODE_INTERPRETER] = "code_interpreter_minimal_reasoning"

            options.update(user_input)
            if not errors:
                if self._is_new:
                    return self.async_create_entry(
                        title=options.pop(CONF_NAME),
                        data=options,
                    )
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    data=options,
                )

        return self.async_show_form(
            step_id="model",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(step_schema), options
            ),
            errors=errors,
        )

    def _get_reasoning_options(self, model: str) -> list[str]:
        """Get reasoning effort options based on model."""
        if not model.startswith(("o", "gpt-5", "gpt-6")) or model.startswith(
            "gpt-5-pro"
        ):
            return []

        models_reasoning_map: dict[str | tuple[str, ...], list[str]] = {
            ("gpt-6-luna", "gpt-6.1-terra"): [
                "none",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
            ],
            "gpt-6": ["low", "medium", "high", "xhigh", "max"],
            "gpt-5.6": ["none", "low", "medium", "high", "xhigh", "max"],
            ("gpt-5.2-pro", "gpt-5.4-pro", "gpt-5.5-pro"): ["medium", "high", "xhigh"],
            ("gpt-5.2", "gpt-5.3", "gpt-5.4", "gpt-5.5"): [
                "none",
                "low",
                "medium",
                "high",
                "xhigh",
            ],
            "gpt-5.1": ["none", "low", "medium", "high"],
            "gpt-5": ["minimal", "low", "medium", "high"],
            "": ["low", "medium", "high"],  # The default case
        }

        for prefix, options in models_reasoning_map.items():
            if model.startswith(prefix):
                return options
        return []  # pragma: no cover

    def _get_service_tiers(self, model: str) -> list[str]:
        """Get service tier options based on model."""
        service_tiers = ["auto"]

        if not model.startswith(tuple(UNSUPPORTED_FLEX_SERVICE_TIERS_MODELS)):
            service_tiers.append("flex")

        service_tiers.append("default")

        if not model.startswith(tuple(UNSUPPORTED_PRIORITY_SERVICE_TIERS_MODELS)):
            service_tiers.append("priority")

        if (
            model in SUPPORTED_ULTRAFAST_MODELS
            or get_base_url(self._get_entry().data) != DEFAULT_BASE_URL
        ):
            service_tiers.append("ultrafast")

        return service_tiers

    async def _get_location_data(self) -> dict[str, str]:
        """Get approximate location data of the user."""
        location_data: dict[str, str] = {}
        zone_home = self.hass.states.get(ENTITY_ID_HOME)
        if zone_home is not None:
            client = create_client(self.hass, self._get_entry().data)
            location_schema = probatio.Schema(
                {
                    probatio.Optional(
                        CONF_WEB_SEARCH_CITY,
                        description=(
                            "Free text input for the city, e.g. `San Francisco`"
                        ),
                    ): str,
                    probatio.Optional(
                        CONF_WEB_SEARCH_REGION,
                        description="Free text input for the region, e.g. `California`",
                    ): str,
                }
            )
            response = await client.responses.create(
                model=RECOMMENDED_CHAT_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": "Where are the following coordinates located: "
                        f"({zone_home.attributes[EntityStateAttribute.LATITUDE]},"
                        f" {zone_home.attributes[EntityStateAttribute.LONGITUDE]})?",
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "approximate_location",
                        "description": "Approximate location data of the user "
                        "for refined web search results",
                        "schema": probatio.to_openapi(
                            location_schema, openapi_version="3.1.0"
                        ),
                        "strict": False,
                    }
                },
                store=self.options.get(
                    CONF_STORE_RESPONSES, RECOMMENDED_STORE_RESPONSES
                ),
            )
            location_data = location_schema(json.loads(response.output_text) or {})

        if self.hass.config.country:
            location_data[CONF_WEB_SEARCH_COUNTRY] = self.hass.config.country
        location_data[CONF_WEB_SEARCH_TIMEZONE] = self.hass.config.time_zone

        _LOGGER.debug("Location data: %s", location_data)

        return location_data


class AudioSubentryFlowHandler(ConfigSubentryFlow):
    """Choose and configure an audio provider for a subentry."""

    options: dict[str, Any]
    openai_options: dict[str, Any]
    openai_name: str
    openai_default_model: str
    openai_models: list[str]
    elevenlabs_name: str
    elevenlabs_default_model: str
    elevenlabs_models: list[str]
    elevenlabs_requires_voice = False

    @abstractmethod
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure the audio subentry for OpenAI."""

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == "user"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add an audio subentry."""
        self.options = self.openai_options.copy()
        return await self.async_step_provider()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an audio subentry."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_provider()

    async def async_step_provider(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose how to process audio."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        provider = self.options.get(CONF_PROVIDER, PROVIDER_OPENAI)
        has_elevenlabs_key = bool(entry.data.get(CONF_ELEVENLABS_API_KEY))
        if user_input is None and not has_elevenlabs_key and provider == PROVIDER_OPENAI:
            return await self.async_step_init()

        if user_input is not None:
            selection = user_input[CONF_PROVIDER]
            if selection == PROVIDER_ELEVENLABS:
                if provider != selection:
                    self.options = {CONF_PROVIDER: selection}
                return await self.async_step_elevenlabs()
            if selection != provider:
                self.options = self.openai_options.copy()
            return await self.async_step_init()

        providers = [PROVIDER_OPENAI]
        if has_elevenlabs_key:
            providers.append(PROVIDER_ELEVENLABS)
        return self.async_show_form(
            step_id="provider",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_PROVIDER,
                        default=provider if provider in providers else PROVIDER_OPENAI,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=providers,
                            translation_key=CONF_PROVIDER,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_elevenlabs(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure a model and, for synthesis, a voice."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        if not entry.data.get(CONF_ELEVENLABS_API_KEY):
            return self.async_abort(reason="elevenlabs_key_required")

        provider_schema: VolDictType = {}
        if self.elevenlabs_requires_voice:
            provider_schema[probatio.Required(CONF_ELEVENLABS_VOICE_ID)] = str
        return self._async_audio_model_form("elevenlabs", provider_schema, user_input)

    def _async_audio_model_form(
        self,
        step_id: str,
        provider_schema: VolDictType,
        user_input: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        """Select a model preset or enter a model ID."""
        elevenlabs = step_id == "elevenlabs"
        models = self.elevenlabs_models if elevenlabs else self.openai_models
        default_model = (
            self.elevenlabs_default_model if elevenlabs else self.openai_default_model
        )
        saved_model = self.options.get(CONF_CHAT_MODEL) or default_model
        saved_choice = saved_model if saved_model in models else OTHER_AUDIO_MODEL
        suggested = self.options | {CONF_CHAT_MODEL: saved_choice}
        if saved_choice == OTHER_AUDIO_MODEL:
            suggested[CONF_CUSTOM_AUDIO_MODEL] = saved_model

        errors: dict[str, str] = {}
        if user_input is not None:
            suggested.update(user_input)
            options = self.options | user_input
            custom_model = options.pop(CONF_CUSTOM_AUDIO_MODEL, "").strip()
            choice = user_input.get(CONF_CHAT_MODEL, saved_choice)
            if choice == OTHER_AUDIO_MODEL:
                suggested[CONF_CUSTOM_AUDIO_MODEL] = custom_model
                if not custom_model:
                    errors[CONF_CUSTOM_AUDIO_MODEL] = "model_required"
                options[CONF_CHAT_MODEL] = custom_model
            else:
                options[CONF_CHAT_MODEL] = choice

            if elevenlabs and self.elevenlabs_requires_voice:
                voice_id = options[CONF_ELEVENLABS_VOICE_ID].strip()
                options[CONF_ELEVENLABS_VOICE_ID] = voice_id
                if not voice_id:
                    errors[CONF_ELEVENLABS_VOICE_ID] = "voice_required"

            if not errors:
                return self._save_options(options)

        step_schema: VolDictType = {}
        if self._is_new:
            default_name = self.elevenlabs_name if elevenlabs else self.openai_name
            step_schema[probatio.Required(CONF_NAME, default=default_name)] = str
        step_schema[probatio.Required(CONF_CHAT_MODEL, default=saved_choice)] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=[*models, OTHER_AUDIO_MODEL],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="audio_model",
                )
            )
        )
        custom_model_selected: FieldCondition = {
            "field": CONF_CHAT_MODEL,
            "value": OTHER_AUDIO_MODEL,
        }
        step_schema[
            data_entry_flow.Optional(
                CONF_CUSTOM_AUDIO_MODEL, visible=custom_model_selected
            )
        ] = str
        step_schema.update(provider_schema)
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(step_schema), suggested
            ),
            errors=errors,
        )

    def _save_options(self, options: dict[str, Any]) -> SubentryFlowResult:
        """Create or update the configured audio subentry."""
        if self._is_new:
            return self.async_create_entry(title=options.pop(CONF_NAME), data=options)
        return self.async_update_and_abort(
            self._get_entry(), self._get_reconfigure_subentry(), data=options
        )


class OpenAISubentrySTTFlowHandler(AudioSubentryFlowHandler):
    """Configure a speech-to-text provider."""

    openai_options = RECOMMENDED_STT_OPTIONS
    openai_name = DEFAULT_STT_NAME
    openai_default_model = RECOMMENDED_STT_MODEL
    openai_models = [
        "gpt-transcribe",
        "gpt-4o-transcribe",
        RECOMMENDED_STT_MODEL,
        "whisper-1",
    ]
    elevenlabs_name = "ElevenLabs Transcrição"
    elevenlabs_default_model = DEFAULT_ELEVENLABS_STT_MODEL
    elevenlabs_models = [DEFAULT_ELEVENLABS_STT_MODEL, "scribe_v3"]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure OpenAI speech recognition."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        provider_schema: VolDictType = {
            probatio.Optional(
                CONF_PROMPT,
                description={
                    "suggested_value": self.options.get(CONF_PROMPT, DEFAULT_STT_PROMPT)
                },
            ): TextSelector(
                TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
            )
        }
        return self._async_audio_model_form("init", provider_schema, user_input)


class OpenAISubentryTTSFlowHandler(AudioSubentryFlowHandler):
    """Configure a text-to-speech provider."""

    openai_options = RECOMMENDED_TTS_OPTIONS
    openai_name = DEFAULT_TTS_NAME
    openai_default_model = RECOMMENDED_TTS_MODEL
    openai_models = [RECOMMENDED_TTS_MODEL, "tts-1", "tts-1-hd"]
    elevenlabs_name = "ElevenLabs Síntese de voz"
    elevenlabs_default_model = DEFAULT_ELEVENLABS_TTS_MODEL
    elevenlabs_models = [
        DEFAULT_ELEVENLABS_TTS_MODEL,
        "eleven_multilingual_v2",
        "eleven_v3",
        "eleven_v4",
    ]
    elevenlabs_requires_voice = True

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure OpenAI speech synthesis."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        provider_schema: VolDictType = {
            probatio.Optional(CONF_PROMPT): TextSelector(
                TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
            ),
            probatio.Optional(
                CONF_TTS_SPEED, default=RECOMMENDED_TTS_SPEED
            ): NumberSelector(NumberSelectorConfig(min=0.25, max=4.0, step=0.01)),
        }
        return self._async_audio_model_form("init", provider_schema, user_input)


class OpenAISubentryEvaluationFlowHandler(ConfigSubentryFlow):
    """Configure an OpenAI evaluation entity."""

    options: dict[str, Any]

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == "user"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add an evaluation task entity."""
        self.options = {CONF_CHAT_MODEL: RECOMMENDED_DECISION_MODEL}
        return await self.async_step_init()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an evaluation task entity."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_init()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure the decision model."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            self.options.update(user_input)
            if self._is_new:
                return self.async_create_entry(
                    title=self.options.pop(CONF_NAME), data=self.options
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=self.options,
            )

        schema: VolDictType = {}
        if self._is_new:
            schema[probatio.Required(CONF_NAME, default=DEFAULT_EVALUATION_NAME)] = str
        schema[probatio.Required(CONF_CHAT_MODEL)] = SelectSelector(
            SelectSelectorConfig(
                options=[RECOMMENDED_DECISION_MODEL],
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(schema), self.options
            ),
        )
