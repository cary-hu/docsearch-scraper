import json

from .. import index


class DummyConfig:
    driver = None
    app_id = "app-id"
    api_key = "api-key"
    index_name = "index-name"
    index_name_tmp = "index-name-tmp"
    query_rules = []
    user_agent = "test-agent"
    use_anchors = False
    extra_records = []
    concurrent_requests = None
    concurrent_requests_per_domain = None
    download_delay = None
    randomize_download_delay = None
    autothrottle_enabled = None

    @staticmethod
    def update_nb_hits_value(_):
        return None


class DummyProcess:
    last_settings = None

    def __init__(self, settings):
        DummyProcess.last_settings = settings

    def crawl(self, *args, **kwargs):
        return None

    def start(self):
        index.DocumentationSpider.NB_INDEXED = 1

    def stop(self):
        return None


class DummyStrategy:
    levels = []


class DummyAlgoliaHelper:
    def commit_tmp_index(self):
        return None

    def add_records(self, *args, **kwargs):
        return None


def test_run_config_adds_x_auth_token_header_from_env(monkeypatch):
    monkeypatch.setenv("X_AUTH_TOKEN", "secret-token")
    monkeypatch.delenv("CF_ACCESS_CLIENT_ID", raising=False)
    monkeypatch.delenv("CF_ACCESS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("IAP_AUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("IAP_AUTH_SERVICE_ACCOUNT_JSON", raising=False)

    monkeypatch.setattr(index, "ConfigLoader", lambda config: DummyConfig())
    monkeypatch.setattr(index, "DefaultStrategy", lambda config: DummyStrategy())
    monkeypatch.setattr(index, "AlgoliaHelper", lambda *args, **kwargs: DummyAlgoliaHelper())
    monkeypatch.setattr(index, "CrawlerProcess", DummyProcess)
    monkeypatch.setattr(index.BrowserHandler, "destroy", lambda driver: None)
    monkeypatch.setattr(index.AlgoliaSettings, "get", lambda config, levels: {})

    index.run_config(json.dumps({"index_name": "index-name"}))

    assert DummyProcess.last_settings["DEFAULT_REQUEST_HEADERS"]["x-auth-token"] == "secret-token"


def test_run_config_applies_rate_limit_settings(monkeypatch):
    config = DummyConfig()
    config.concurrent_requests = 4
    config.concurrent_requests_per_domain = 1
    config.download_delay = 1.5
    config.randomize_download_delay = False
    config.autothrottle_enabled = True

    monkeypatch.setattr(index, "ConfigLoader", lambda config_payload: config)
    monkeypatch.setattr(index, "DefaultStrategy", lambda config_payload: DummyStrategy())
    monkeypatch.setattr(index, "AlgoliaHelper", lambda *args, **kwargs: DummyAlgoliaHelper())
    monkeypatch.setattr(index, "CrawlerProcess", DummyProcess)
    monkeypatch.setattr(index.BrowserHandler, "destroy", lambda driver: None)
    monkeypatch.setattr(index.AlgoliaSettings, "get", lambda config_payload, levels: {})

    index.run_config(json.dumps({"index_name": "index-name"}))

    assert DummyProcess.last_settings["CONCURRENT_REQUESTS"] == 4
    assert DummyProcess.last_settings["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert DummyProcess.last_settings["DOWNLOAD_DELAY"] == 1.5
    assert DummyProcess.last_settings["RANDOMIZE_DOWNLOAD_DELAY"] is False
    assert DummyProcess.last_settings["AUTOTHROTTLE_ENABLED"] is True
