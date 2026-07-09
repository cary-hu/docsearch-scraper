import json

from .. import index
from ..algolia_diff import add_content_hash


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
    update_mode = "atomic"
    incremental_dry_run = False
    max_delete_ratio = 0.2
    max_delete_count = None
    diff_report_path = None
    synonyms = {}

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
    def __init__(self):
        self.committed = False
        self.deleted = []
        self.saved = []
        self.settings_applied = False
        self.rules_applied = False
        self.synonyms_applied = False
        self.collected_records = []
        self.old_records = []

    def commit_tmp_index(self):
        self.committed = True
        return None

    def add_records(self, *args, **kwargs):
        return None

    def get_collected_records(self):
        return list(self.collected_records)

    def browse_existing_records(self):
        return list(self.old_records)

    def delete_records(self, object_ids):
        self.deleted.extend(object_ids)

    def save_records(self, records):
        self.saved.extend(records)

    def apply_settings(self, _):
        self.settings_applied = True

    def apply_rules(self, _):
        self.rules_applied = True

    def apply_synonyms(self, _):
        self.synonyms_applied = True


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


def test_run_config_atomic_commits_tmp_index(monkeypatch):
    helper = DummyAlgoliaHelper()

    monkeypatch.setattr(index, "ConfigLoader", lambda config: DummyConfig())
    monkeypatch.setattr(index, "DefaultStrategy", lambda config: DummyStrategy())
    monkeypatch.setattr(index, "AlgoliaHelper", lambda *args, **kwargs: helper)
    monkeypatch.setattr(index, "CrawlerProcess", DummyProcess)
    monkeypatch.setattr(index.BrowserHandler, "destroy", lambda driver: None)
    monkeypatch.setattr(index.AlgoliaSettings, "get", lambda config, levels: {})

    index.run_config(json.dumps({"index_name": "index-name"}))

    assert helper.committed is True


def test_run_config_incremental_dry_run_writes_no_changes(monkeypatch, tmpdir,
                                                          capsys):
    config = DummyConfig()
    config.update_mode = "incremental"
    config.incremental_dry_run = True
    config.diff_report_path = str(tmpdir.join("report.json"))
    helper = DummyAlgoliaHelper()
    helper.collected_records = [{
        "objectID": "new",
        "url": "https://example.com/new",
        "content": "New",
    }]

    monkeypatch.setattr(index, "ConfigLoader", lambda config_payload: config)
    monkeypatch.setattr(index, "DefaultStrategy", lambda config_payload: DummyStrategy())
    monkeypatch.setattr(index, "AlgoliaHelper", lambda *args, **kwargs: helper)
    monkeypatch.setattr(index, "CrawlerProcess", DummyProcess)
    monkeypatch.setattr(index.BrowserHandler, "destroy", lambda driver: None)
    monkeypatch.setattr(index.AlgoliaSettings, "get", lambda config_payload, levels: {})

    index.run_config(json.dumps({"index_name": "index-name"}))

    assert helper.deleted == []
    assert helper.saved == []
    assert helper.settings_applied is False
    assert tmpdir.join("report.json").check()
    captured = capsys.readouterr()
    assert "Incremental diff report:" in captured.out
    assert '"to_add_count": 1' in captured.out


def test_run_config_incremental_write_deletes_and_saves(monkeypatch, tmpdir):
    config = DummyConfig()
    config.update_mode = "incremental"
    config.incremental_dry_run = False
    config.max_delete_ratio = 1.0
    config.diff_report_path = str(tmpdir.join("report.json"))
    helper = DummyAlgoliaHelper()
    helper.old_records = [
        add_content_hash({
            "objectID": "delete",
            "url": "https://example.com/delete",
            "content": "Gone",
        }),
        add_content_hash({
            "objectID": "update",
            "url": "https://example.com/update",
            "content": "Before",
        }),
    ]
    helper.collected_records = [
        {
            "objectID": "add",
            "url": "https://example.com/add",
            "content": "New",
        },
        {
            "objectID": "update",
            "url": "https://example.com/update",
            "content": "After",
        },
    ]

    monkeypatch.setattr(index, "ConfigLoader", lambda config_payload: config)
    monkeypatch.setattr(index, "DefaultStrategy", lambda config_payload: DummyStrategy())
    monkeypatch.setattr(index, "AlgoliaHelper", lambda *args, **kwargs: helper)
    monkeypatch.setattr(index, "CrawlerProcess", DummyProcess)
    monkeypatch.setattr(index.BrowserHandler, "destroy", lambda driver: None)
    monkeypatch.setattr(index.AlgoliaSettings, "get", lambda config_payload, levels: {})

    index.run_config(json.dumps({"index_name": "index-name"}))

    assert helper.deleted == ["delete"]
    assert [record["objectID"] for record in helper.saved] == ["add", "update"]
    assert helper.settings_applied is True
    assert helper.rules_applied is True
    assert helper.synonyms_applied is True
    assert tmpdir.join("report.json").check()
