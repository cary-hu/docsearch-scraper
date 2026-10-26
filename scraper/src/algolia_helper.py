"""AlgoliaHelper
Wrapper on top of the AlgoliaSearch API client"""

import re

from algoliasearch.search_client import SearchClient

from builtins import range

from .algolia_diff import CONTENT_HASH_FIELD
from .record_size import (
    MAX_RECORD_SIZE_BYTES,
    fit_record_to_size,
    record_size_bytes,
    split_record,
)

INDEX_NOT_FOUND_STATUS_CODE = 404

# Matches messages such as "Index phx-zhiqi-cn does not exist" or
# "Index phx-zhiqi-cn not found".
INDEX_NOT_FOUND_MESSAGE_RE = re.compile(
    r'index\b.*\b(does not exist|not found)', re.IGNORECASE)


def is_index_not_found_error(error):
    """Return True when an Algolia error means the index does not exist."""
    status_code = getattr(error, 'status_code', None)
    if status_code is not None:
        return status_code == INDEX_NOT_FOUND_STATUS_CODE

    # Fallback for clients that do not expose the HTTP status code.
    message = str(getattr(error, 'message', None) or error)
    return bool(INDEX_NOT_FOUND_MESSAGE_RE.search(message))


class AlgoliaHelper:
    """AlgoliaHelper"""

    def __init__(self, app_id, api_key, index_name, index_name_tmp, settings,
                 query_rules, update_mode='atomic'):
        self.algolia_client = SearchClient.create(app_id, api_key)
        self.index_name = index_name
        self.index_name_tmp = index_name_tmp
        self.settings = settings
        self.query_rules = query_rules
        self.update_mode = update_mode
        self.collected_records = []
        self.index_missing = False
        self.algolia_index = self.algolia_client.init_index(self.index_name)
        self.algolia_index_tmp = None

        if self.update_mode == 'atomic':
            self.algolia_index_tmp = self.algolia_client.init_index(
                self.index_name_tmp)
            self.algolia_client.copy_rules(
                self.index_name,
                self.index_name_tmp
            )
            self.algolia_index_tmp.set_settings(settings)

            if len(query_rules) > 0:
                self._save_rules(self.algolia_index_tmp, query_rules)
        elif self.update_mode != 'incremental':
            raise ValueError('update_mode must be atomic or incremental')

    def add_records(self, records, url, from_sitemap):
        """Add new records to Algolia or collect them for incremental mode."""
        # Crawled records are already split by the strategy; this also covers
        # `extra_records`. It is a no-op for records that fit.
        records = [
            chunk for record in records for chunk in split_record(record)
        ]
        record_count = len(records)

        if self.update_mode == 'incremental':
            self.collected_records.extend(records)
        else:
            self._save_records_to_index(self.algolia_index_tmp, records)

        color = "96" if from_sitemap else "94"

        print(
            '\033[{}m> DocSearch: \033[0m{}\033[93m {} records\033[0m)'.format(
                color, url, record_count))

    def get_collected_records(self):
        return list(self.collected_records)

    def add_synonyms(self, synonyms):
        synonyms_list = self._normalize_synonyms(synonyms)

        target_index = self.algolia_index_tmp
        if self.update_mode == 'incremental':
            target_index = self.algolia_index

        target_index.save_synonyms(synonyms_list)
        print(
            '\033[94m> DocSearch: \033[0m Synonyms (\033[93m{} synonyms\033[0m)'.format(
                len(synonyms_list)))

    def browse_existing_records(self):
        """Return the records currently stored in the index.

        When the index does not exist yet, an empty list is returned and
        `index_missing` is set so callers can treat the crawl as a full
        initial import instead of failing.
        """
        request_options = {
            'attributesToRetrieve': [
                'objectID',
                'url',
                CONTENT_HASH_FIELD
            ]
        }

        self.index_missing = False
        records = []

        try:
            for record in self.algolia_index.browse_objects(request_options):
                records.append(record)
        except Exception as error:
            if records or not is_index_not_found_error(error):
                raise

            self.index_missing = True
            print(
                '\033[93m> DocSearch: \033[0m{} does not exist yet, '
                'the index will be created\033[0m'.format(self.index_name))
            return []

        return records

    def save_records(self, records):
        self._save_records_to_index(self.algolia_index, records)

    def delete_records(self, object_ids):
        object_ids = list(object_ids)

        for i in range(0, len(object_ids), 50):
            self.algolia_index.delete_objects(object_ids[i:i + 50])

    def apply_settings(self, settings=None):
        settings = self.settings if settings is None else settings
        self.algolia_index.set_settings(settings)

    def apply_rules(self, query_rules=None):
        query_rules = self.query_rules if query_rules is None else query_rules
        if len(query_rules) > 0:
            self._save_rules(self.algolia_index, query_rules)

    def apply_synonyms(self, synonyms):
        synonyms_list = self._normalize_synonyms(synonyms)
        if len(synonyms_list) > 0:
            self.algolia_index.save_synonyms(synonyms_list)

    def commit_tmp_index(self):
        """Overwrite the real index with the temporary one"""
        # print("Update settings")
        self.algolia_client.move_index(self.index_name_tmp, self.index_name)

    @staticmethod
    def _normalize_synonyms(synonyms):
        if synonyms is None:
            return []
        if isinstance(synonyms, dict):
            return [value for _, value in list(synonyms.items())]
        return list(synonyms)

    def _save_records_to_index(self, index, records):
        records = self._fit_records_to_size(records)
        record_count = len(records)
        for i in range(0, record_count, 50):
            index.save_objects(records[i:i + 50])

    @staticmethod
    def _fit_records_to_size(records):
        """Shorten records that would be rejected by the Algolia size limit."""
        fitted_records = []
        for record in records:
            fitted = fit_record_to_size(record)
            if fitted is not record:
                trimmed_size = record_size_bytes(fitted)
                print(
                    '\033[93m> DocSearch: \033[0mrecord {} ({}) is {} bytes, '
                    'shortened to {} bytes to fit the Algolia record size '
                    'limit'.format(
                        record.get('objectID'),
                        record.get('url'),
                        record_size_bytes(record),
                        trimmed_size))
                if trimmed_size > MAX_RECORD_SIZE_BYTES:
                    print(
                        '\033[91m> DocSearch: \033[0mrecord {} is still {} '
                        'bytes after trimming, Algolia will reject it. Check '
                        'the number of attributes of that page.'.format(
                            record.get('objectID'), trimmed_size))
            fitted_records.append(fitted)
        return fitted_records

    def _save_rules(self, index, query_rules):
        try:
            index.save_rules(query_rules, True, True)
        except TypeError:
            index.save_rules(query_rules)
