"""
DocSearch scraper main entry point
"""
import os
import json
import requests
from requests_iap import IAPAuth

from scrapy.crawler import CrawlerProcess

from .algolia_helper import AlgoliaHelper
from .config.config_loader import ConfigLoader
from .documentation_spider import DocumentationSpider
from .strategies.default_strategy import DefaultStrategy
from .custom_downloader_middleware import CustomDownloaderMiddleware
from .custom_dupefilter import CustomDupeFilter
from .config.browser_handler import BrowserHandler
from .strategies.algolia_settings import AlgoliaSettings
from .algolia_diff import (
    IncrementalUpdateError,
    add_content_hashes,
    build_diff_report,
    diff_records,
    find_duplicate_object_ids,
    print_diff_report,
    validate_incremental_update,
    write_diff_report,
)

try:
    # disable boto (S3 download)
    from scrapy import optional_features

    if 'boto' in optional_features:
        optional_features.remove('boto')
except ImportError:
    pass

EXIT_CODE_NO_RECORD = 3


def run_config(config):
    config = ConfigLoader(config)
    CustomDownloaderMiddleware.driver = config.driver
    DocumentationSpider.NB_INDEXED = 0

    strategy = DefaultStrategy(config)
    settings = AlgoliaSettings.get(config, strategy.levels)

    algolia_helper = AlgoliaHelper(
        config.app_id,
        config.api_key,
        config.index_name,
        config.index_name_tmp,
        settings,
        config.query_rules,
        config.update_mode
    )

    root_module = 'src.' if __name__ == '__main__' else 'scraper.src.'
    DOWNLOADER_MIDDLEWARES_PATH = root_module + 'custom_downloader_middleware.' + CustomDownloaderMiddleware.__name__
    DUPEFILTER_CLASS_PATH = root_module + 'custom_dupefilter.' + CustomDupeFilter.__name__

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en",
    }  # Defaults for scrapy https://docs.scrapy.org/en/latest/topics/settings.html#default-request-headers

    if os.getenv("X_AUTH_TOKEN"):
        headers.update({"x-auth-token": os.getenv("X_AUTH_TOKEN")})

    if os.getenv("CF_ACCESS_CLIENT_ID") and os.getenv("CF_ACCESS_CLIENT_SECRET"):
        headers.update(
            {
                "CF-Access-Client-Id": os.getenv("CF_ACCESS_CLIENT_ID"),
                "CF-Access-Client-Secret": os.getenv("CF_ACCESS_CLIENT_SECRET"),
            }
        )
    elif os.getenv("IAP_AUTH_CLIENT_ID") and os.getenv("IAP_AUTH_SERVICE_ACCOUNT_JSON"):
        iap_token = IAPAuth(
            client_id=os.getenv("IAP_AUTH_CLIENT_ID"),
            service_account_secret_dict=json.loads(
                os.getenv("IAP_AUTH_SERVICE_ACCOUNT_JSON")
            ),
        )(requests.Request()).headers["Authorization"]
        headers.update({"Authorization": iap_token})

    DEFAULT_REQUEST_HEADERS = headers

    crawler_settings = {
        'LOG_ENABLED': '1',
        'LOG_LEVEL': 'ERROR',
        'USER_AGENT': config.user_agent,
        'DOWNLOADER_MIDDLEWARES': {DOWNLOADER_MIDDLEWARES_PATH: 900},
        # Need to be > 600 to be after the redirectMiddleware
        'DUPEFILTER_USE_ANCHORS': config.use_anchors,
        # Use our custom dupefilter in order to be scheme agnostic regarding link provided
        'DUPEFILTER_CLASS': DUPEFILTER_CLASS_PATH,
        'DEFAULT_REQUEST_HEADERS': DEFAULT_REQUEST_HEADERS,
        'TELNETCONSOLE_ENABLED': False
    }

    if config.concurrent_requests is not None:
        crawler_settings['CONCURRENT_REQUESTS'] = config.concurrent_requests
    if config.concurrent_requests_per_domain is not None:
        crawler_settings['CONCURRENT_REQUESTS_PER_DOMAIN'] = config.concurrent_requests_per_domain
    if config.download_delay is not None:
        crawler_settings['DOWNLOAD_DELAY'] = config.download_delay
    if config.randomize_download_delay is not None:
        crawler_settings['RANDOMIZE_DOWNLOAD_DELAY'] = config.randomize_download_delay
    if config.autothrottle_enabled is not None:
        crawler_settings['AUTOTHROTTLE_ENABLED'] = config.autothrottle_enabled

    process = CrawlerProcess(crawler_settings)

    process.crawl(
        DocumentationSpider,
        config=config,
        algolia_helper=algolia_helper,
        strategy=strategy
    )

    process.start()
    process.stop()

    # Kill browser if needed
    BrowserHandler.destroy(config.driver)

    if len(config.extra_records) > 0:
        algolia_helper.add_records(config.extra_records, "Extra records", False)

    print("")

    if DocumentationSpider.NB_INDEXED > 0:
        if config.update_mode == 'incremental':
            _run_incremental_update(config, algolia_helper, settings)
        else:
            algolia_helper.commit_tmp_index()
        print('Nb hits: {}'.format(DocumentationSpider.NB_INDEXED))
        config.update_nb_hits_value(DocumentationSpider.NB_INDEXED)
    else:
        print('Crawling issue: nbHits 0 for ' + config.index_name)
        exit(EXIT_CODE_NO_RECORD)
    print("")


def _run_incremental_update(config, algolia_helper, settings):
    new_records = add_content_hashes(algolia_helper.get_collected_records())
    old_records = algolia_helper.browse_existing_records()
    duplicate_object_ids = find_duplicate_object_ids(new_records)

    try:
        diff = diff_records(old_records, new_records)
    except IncrementalUpdateError as error:
        diff = {
            "to_add": [],
            "to_update": [],
            "to_delete": [],
            "unchanged": 0,
        }
        report = build_diff_report(
            config.index_name, len(old_records), len(new_records), diff)
        if duplicate_object_ids:
            report["duplicate_object_ids"] = duplicate_object_ids
        report["error"] = str(error)
        report_path = _write_and_print_diff_report(
            report, config.diff_report_path)
        raise IncrementalUpdateError(
            "Incremental update aborted before diff could be applied. Report: {}".format(
                report_path
            )
        )

    report = build_diff_report(
        config.index_name, len(old_records), len(new_records), diff)
    report_path = write_diff_report(report, config.diff_report_path)

    try:
        validate_incremental_update(
            diff,
            len(old_records),
            len(new_records),
            config.max_delete_ratio,
            config.max_delete_count
        )
    except IncrementalUpdateError as error:
        report["error"] = str(error)
        _write_and_print_diff_report(report, config.diff_report_path)
        raise

    if config.incremental_dry_run:
        print_diff_report(report)
        print(
            "Incremental dry-run: +{} ~{} -{} unchanged {}. Report: {}".format(
                len(diff["to_add"]),
                len(diff["to_update"]),
                len(diff["to_delete"]),
                diff["unchanged"],
                report_path
            )
        )
        return

    algolia_helper.delete_records([
        record["objectID"] for record in diff["to_delete"]
    ])
    algolia_helper.save_records(diff["to_add"] + diff["to_update"])
    algolia_helper.apply_settings(settings)
    algolia_helper.apply_rules(config.query_rules)

    if hasattr(config, "synonyms"):
        algolia_helper.apply_synonyms(config.synonyms)

    print_diff_report(report)
    print(
        "Incremental update: +{} ~{} -{} unchanged {}. Report: {}".format(
            len(diff["to_add"]),
            len(diff["to_update"]),
            len(diff["to_delete"]),
            diff["unchanged"],
            report_path
        )
    )


def _write_and_print_diff_report(report, report_path):
    written_report_path = write_diff_report(report, report_path)
    print_diff_report(report)
    return written_report_path


if __name__ == '__main__':
    from os import environ

    run_config(environ['CONFIG'])
