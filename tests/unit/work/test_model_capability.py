from octop_harness.config import ModelConfig, ProviderConfig
from octop_harness.llm.factory import ChatModelFactory

from octop.infra.work.middleware import _model_capability


def test_installed_harness_openai_subclass_keeps_provider_identity():
    factory = ChatModelFactory(
        [
            ProviderConfig(
                id="local",
                protocol="openai",
                api_key="synthetic-only",
                base_url="http://127.0.0.1:9/v1",
                models=[ModelConfig(id="test-model")],
            )
        ]
    )
    model = factory.get_chat_model("local/test-model")
    assert _model_capability(model) == "model:openai/test-model"
