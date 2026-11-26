# OpenAI Personalizado para Home Assistant

Integração personalizada para usar agentes de conversa e tarefas de IA da OpenAI no Home Assistant, com OpenAI ou ElevenLabs para transcrição e síntese de voz.

## Instalação pelo Marketplace

Requer Home Assistant Core 2026.11.2 ou posterior.

1. Abra o [OpenAI Personalizado no Marketplace](https://my.home-assistant.io/redirect/marketplace_repository/?owner=caduosmarini&repository=hass-openai&category=integration).
2. Conecte o GitHub se solicitado. Também é possível adicionar `caduosmarini/hass-openai` em **Configurações → Marketplace → Adicionar por link**.
3. Selecione **Instalar**. Ao abrir a configuração da integração, informe a chave da API. A chave da ElevenLabs é opcional.

## Instalação manual

1. Copie a pasta `custom_components/hass_openai` para `/config/custom_components/hass_openai` na sua instalação.
2. Reinicie o Home Assistant.
3. Em **Configurações → Dispositivos e serviços → Adicionar integração**, procure **OpenAI Personalizado** e informe a chave da API. [Como criar uma chave de API da OpenAI](https://www.home-assistant.io/integrations/openai_conversation/#prerequisites).
4. Para usar o agente no Assist, selecione a entidade de conversa da integração personalizada em **Configurações → Assistentes de voz**.

O domínio `hass_openai` permite instalar a integração ao lado da oficial. As entradas de configuração são independentes.

## URL da API e Ultrafast

- **URL base da API**. Deixe em branco para usar `https://api.openai.com/v1`. Para um serviço compatível, informe a URL base completa (por exemplo, `https://api.exemplo.com/v1`) e a chave desse serviço. Para editar a URL de uma conta já criada, abra **Reconfigurar** na entrada da integração.
- **Ultrafast**. Na configuração do agente de conversa ou da tarefa de IA, desative as configurações recomendadas, selecione o modelo e escolha **Ultrafast** no nível de serviço. Na OpenAI, a opção aparece para os modelos compatíveis. Em um serviço alternativo, a disponibilidade depende do provedor e do modelo. [Modo Ultrafast da OpenAI](https://developers.openai.com/api/docs/guides/ultrafast-mode)

## Áudio com ElevenLabs

1. Na entrada **OpenAI Personalizado**, abra **Reconfigurar** e informe a **Chave de API da ElevenLabs**. A chave também pode ser informada ao instalar a integração. Se a URL da OpenAI continuar a mesma, o campo da chave principal pode ficar vazio para manter o valor salvo.
2. Adicione ou reconfigure um serviço de **Conversão de fala em texto** e selecione **ElevenLabs**. Escolha um modelo, como `scribe_v2` ou `scribe_v3`. [API de transcrição](https://elevenlabs.io/docs/api-reference/speech-to-text/convert)
3. Para **Conversão de texto em fala**, selecione **ElevenLabs**, escolha um modelo de síntese e informe o ID de uma voz da sua conta. O modelo sugerido é `eleven_flash_v2_5`. [API de síntese de voz](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
4. Em **Configurações → Assistentes de voz**, selecione os serviços de transcrição e síntese que deseja usar no Assist. Você pode usar os provedores de forma independente.

Use uma chave da ElevenLabs com permissão para as funções escolhidas. A API verifica a chave quando o serviço de áudio é usado.

## Escolher um modelo de áudio

Ao adicionar ou reconfigurar um serviço de transcrição ou síntese de voz, escolha o provedor e selecione um dos modelos da lista. Para usar outro modelo compatível com a API do provedor, escolha **Outro** e informe o ID exato.

A OpenAI anunciou o encerramento de GPT-4o mini TTS, TTS-1 e TTS-1 HD em 6 de janeiro de 2027. [Referência da API de síntese](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)

## Código de origem

Esta versão deriva da [integração oficial OpenAI no Home Assistant Core 2026.11.3](https://github.com/home-assistant/core/tree/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/openai_conversation). A pasta `translations` inclui textos em inglês e português do Brasil.

Código distribuído sob a [licença Apache 2.0](LICENSE.md).
