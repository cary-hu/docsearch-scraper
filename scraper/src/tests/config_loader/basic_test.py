# coding: utf-8
from ...config.config_loader import ConfigLoader
from .abstract import config
import pytest


class TestInit:
    @staticmethod
    def test_need_json_env_var():
        """ Should throw if CONFIG is not JSON """
        # Given
        c = 'foobar'

        # When / Then
        with pytest.raises(ValueError):
            ConfigLoader(c)

    def test_mandatory_index_name(self):
        """ Should throw if no index_name passed """
        # Given
        c = config({
            'index_name': None
        })

        # When / Then
        with pytest.raises(ValueError):
            ConfigLoader(c)

    def test_correct_new_naming_scrape(self):
        """ Old variable scrap_url must be spread to scrape_url. If one is defined, the previous one must be used"""
        # Given
        c = config({
            'scrap_start_urls': False
        })

        config_loaded = ConfigLoader(c)

        assert config_loaded.scrape_start_urls == False
        assert config_loaded.scrap_start_urls == config_loaded.scrape_start_urls

    def test_excpetion_when_shadowing_(self):
        """ User must use the last attribute name: scrape_start_urls, not both (BC). This error must be raised"""
        # Given
        c = config({
            'scrap_start_urls': False,
            'scrape_start_urls': False
        })

        with pytest.raises(Exception):
            ConfigLoader(c)

    def test_update_mode_defaults_to_atomic(self, monkeypatch):
        monkeypatch.delenv('DOCSEARCH_UPDATE_MODE', raising=False)
        monkeypatch.delenv('DOCSEARCH_INCREMENTAL_DRY_RUN', raising=False)

        config_loaded = ConfigLoader(config())

        assert config_loaded.update_mode == 'atomic'
        assert config_loaded.incremental_dry_run is False

    def test_incremental_mode_defaults_to_dry_run(self, monkeypatch):
        monkeypatch.setenv('DOCSEARCH_UPDATE_MODE', 'incremental')
        monkeypatch.delenv('DOCSEARCH_INCREMENTAL_DRY_RUN', raising=False)

        config_loaded = ConfigLoader(config())

        assert config_loaded.update_mode == 'incremental'
        assert config_loaded.incremental_dry_run is True

    def test_incremental_dry_run_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv('DOCSEARCH_UPDATE_MODE', 'incremental')
        monkeypatch.setenv('DOCSEARCH_INCREMENTAL_DRY_RUN', 'false')

        config_loaded = ConfigLoader(config())

        assert config_loaded.incremental_dry_run is False

    def test_invalid_update_mode_raises(self, monkeypatch):
        monkeypatch.setenv('DOCSEARCH_UPDATE_MODE', 'sideways')

        with pytest.raises(ValueError):
            ConfigLoader(config())
