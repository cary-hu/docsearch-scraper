import pytest

pytest.importorskip('algoliasearch')

from algoliasearch.exceptions import RequestException

from ..algolia_helper import AlgoliaHelper, is_index_not_found_error


class FakeIndex:
    def __init__(self, error=None, records=None):
        self.error = error
        self.records = records or []
        self.calls = 0

    def browse_objects(self, request_options):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return iter(self.records)


def _build_helper():
    return AlgoliaHelper(
        'app-id',
        'api-key',
        'index-name',
        'index-name-tmp',
        {},
        [],
        'incremental'
    )


def test_is_index_not_found_error_detects_status_code():
    assert is_index_not_found_error(RequestException('Index not found', 404))
    assert not is_index_not_found_error(RequestException('Forbidden', 403))
    # A definitive non-404 status always wins over the message.
    assert not is_index_not_found_error(
        RequestException('Index phx-zhiqi-cn does not exist', 403))


def test_is_index_not_found_error_detects_message():
    # Real Algolia 404 message, also matched without a status code.
    assert is_index_not_found_error(
        RequestException('Index phx-zhiqi-cn does not exist', None))
    assert is_index_not_found_error(
        RequestException('Index phx-zhiqi-cn does not exist', 404))
    assert is_index_not_found_error(Exception('Index does not exist'))
    assert is_index_not_found_error(Exception('Index phx-zhiqi-cn not found'))
    assert not is_index_not_found_error(Exception('Internal error'))
    assert not is_index_not_found_error(
        Exception('Method not allowed on index phx-zhiqi-cn'))


def test_browse_existing_records_returns_empty_when_index_missing(capsys):
    helper = _build_helper()
    helper.algolia_index = FakeIndex(
        error=RequestException('Index phx-zhiqi-cn does not exist', 404))

    assert helper.browse_existing_records() == []
    assert helper.index_missing is True
    assert 'will be created' in capsys.readouterr().out


def test_browse_existing_records_returns_empty_when_no_status_code(capsys):
    helper = _build_helper()
    helper.algolia_index = FakeIndex(
        error=RequestException('Index phx-zhiqi-cn does not exist', None))

    assert helper.browse_existing_records() == []
    assert helper.index_missing is True
    assert 'will be created' in capsys.readouterr().out


def test_browse_existing_records_propagates_other_errors():
    helper = _build_helper()
    helper.algolia_index = FakeIndex(
        error=RequestException('Invalid Application-ID or API key', 403))

    with pytest.raises(RequestException):
        helper.browse_existing_records()

    assert helper.index_missing is False


def test_browse_existing_records_returns_records():
    helper = _build_helper()
    helper.algolia_index = FakeIndex(records=[{'objectID': 'a'}])

    assert helper.browse_existing_records() == [{'objectID': 'a'}]
    assert helper.index_missing is False
