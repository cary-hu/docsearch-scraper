# coding: utf-8
from ...config.config_loader import ConfigLoader
from .abstract import config


class TestRateLimitConfig:
    def test_reads_rate_limit_settings_from_config(self):
        actual = ConfigLoader(config({
            'concurrent_requests': 4,
            'concurrent_requests_per_domain': 1,
            'download_delay': 1.5,
            'randomize_download_delay': False,
            'autothrottle_enabled': True
        }))

        assert actual.concurrent_requests == 4
        assert actual.concurrent_requests_per_domain == 1
        assert actual.download_delay == 1.5
        assert actual.randomize_download_delay is False
        assert actual.autothrottle_enabled is True

    def test_environment_overrides_rate_limit_settings(self, monkeypatch):
        monkeypatch.setenv("DOCSEARCH_CONCURRENT_REQUESTS", "2")
        monkeypatch.setenv("DOCSEARCH_CONCURRENT_REQUESTS_PER_DOMAIN", "1")
        monkeypatch.setenv("DOCSEARCH_DOWNLOAD_DELAY", "0.75")
        monkeypatch.setenv("DOCSEARCH_RANDOMIZE_DOWNLOAD_DELAY", "false")
        monkeypatch.setenv("DOCSEARCH_AUTOTHROTTLE_ENABLED", "true")

        actual = ConfigLoader(config({
            'concurrent_requests': 4,
            'concurrent_requests_per_domain': 3,
            'download_delay': 1.5,
            'randomize_download_delay': True,
            'autothrottle_enabled': False
        }))

        assert actual.concurrent_requests == 2
        assert actual.concurrent_requests_per_domain == 1
        assert actual.download_delay == 0.75
        assert actual.randomize_download_delay is False
        assert actual.autothrottle_enabled is True
