"""AlgoliaHelper
Wrapper on top of the AlgoliaSearch API client"""

from algoliasearch.search_client import SearchClient

from builtins import range

from .algolia_diff import CONTENT_HASH_FIELD


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
        self.algolia_index = self.algolia_client.init_index(self.index_name)
        self.algolia_index_tmp = None

        if self.update_mode == 'atomic':
            self.algolia_index_tmp = self.algolia_client.init_index(
                self.index_name_tmp)
            self._wait_response(self.algolia_client.copy_rules(
                self.index_name,
                self.index_name_tmp
            ))
            self._wait_response(self.algolia_index_tmp.set_settings(settings))

            if len(query_rules) > 0:
                self._save_rules(self.algolia_index_tmp, query_rules)
        elif self.update_mode != 'incremental':
            raise ValueError('update_mode must be atomic or incremental')

    def add_records(self, records, url, from_sitemap):
        """Add new records to Algolia or collect them for incremental mode."""
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

        self._wait_response(target_index.save_synonyms(synonyms_list))
        print(
            '\033[94m> DocSearch: \033[0m Synonyms (\033[93m{} synonyms\033[0m)'.format(
                len(synonyms_list)))

    def browse_existing_records(self):
        request_options = {
            'attributesToRetrieve': [
                'objectID',
                'url',
                CONTENT_HASH_FIELD
            ]
        }
        return list(self.algolia_index.browse_objects(request_options))

    def save_records(self, records):
        self._save_records_to_index(self.algolia_index, records)

    def delete_records(self, object_ids):
        object_ids = list(object_ids)

        for i in range(0, len(object_ids), 50):
            self._wait_response(
                self.algolia_index.delete_objects(object_ids[i:i + 50])
            )

    def apply_settings(self, settings=None):
        settings = self.settings if settings is None else settings
        self._wait_response(self.algolia_index.set_settings(settings))

    def apply_rules(self, query_rules=None):
        query_rules = self.query_rules if query_rules is None else query_rules
        if len(query_rules) > 0:
            self._save_rules(self.algolia_index, query_rules)

    def apply_synonyms(self, synonyms):
        synonyms_list = self._normalize_synonyms(synonyms)
        if len(synonyms_list) > 0:
            self._wait_response(self.algolia_index.save_synonyms(synonyms_list))

    def commit_tmp_index(self):
        """Overwrite the real index with the temporary one"""
        # print("Update settings")
        self._wait_response(
            self.algolia_client.move_index(self.index_name_tmp, self.index_name)
        )

    @staticmethod
    def _normalize_synonyms(synonyms):
        if synonyms is None:
            return []
        if isinstance(synonyms, dict):
            return [value for _, value in list(synonyms.items())]
        return list(synonyms)

    def _save_records_to_index(self, index, records):
        record_count = len(records)
        for i in range(0, record_count, 50):
            self._wait_response(index.save_objects(records[i:i + 50]))

    def _save_rules(self, index, query_rules):
        try:
            response = index.save_rules(query_rules, True, True)
        except TypeError:
            response = index.save_rules(query_rules)
        self._wait_response(response)

    @staticmethod
    def _wait_response(response):
        if hasattr(response, 'wait'):
            response.wait()
