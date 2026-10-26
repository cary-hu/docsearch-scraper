import json

from ..record_size import (
    MAX_RECORD_SIZE_BYTES,
    fit_record_to_size,
    record_size_bytes,
    split_record,
    split_text,
    truncate_utf8,
)


def _record_with_content(content, **overrides):
    record = {
        'objectID': 'dc1029e163a95919149df4a3fe1fe2a1b2672461',
        'anchor': None,
        'content': content,
        'content_camel': content,
        'hierarchy': {
            'lvl0': 'Getting started',
            'lvl1': 'Configuration',
            'lvl2': None,
            'lvl3': None,
            'lvl4': None,
            'lvl5': None,
            'lvl6': None,
        },
        'type': 'content',
        'url': 'https://example.com/docs/getting-started#configuration',
        'url_without_variables': 'https://example.com/docs/getting-started#configuration',
        'url_without_anchor': 'https://example.com/docs/getting-started',
        'weight': {'page_rank': 0, 'level': 0, 'position': 3},
    }
    record.update(overrides)
    return record


def test_small_record_is_returned_unchanged():
    record = _record_with_content('short content')
    assert fit_record_to_size(record) is record


def test_record_size_matches_json_utf8_size():
    record = _record_with_content('é' * 10)
    expected = len(json.dumps(record).encode('utf-8'))
    assert record_size_bytes(record) == expected


def test_oversized_record_is_shortened_below_the_limit():
    record = _record_with_content('docsearch ' * 2000)
    assert record_size_bytes(record) > MAX_RECORD_SIZE_BYTES

    fitted = fit_record_to_size(record)

    assert record_size_bytes(fitted) <= MAX_RECORD_SIZE_BYTES
    # The original record is not mutated: incremental mode keeps using it.
    assert record_size_bytes(record) > MAX_RECORD_SIZE_BYTES


def test_content_is_trimmed_first_and_identifiers_are_kept():
    record = _record_with_content('x' * 20000)
    fitted = fit_record_to_size(record)

    assert fitted['objectID'] == record['objectID']
    assert fitted['url'] == record['url']
    assert fitted['url_without_anchor'] == record['url_without_anchor']
    assert fitted['anchor'] == record['anchor']
    assert fitted['hierarchy'] == record['hierarchy']
    assert len(fitted['content']) < len(record['content'])
    assert len(fitted['content_camel']) < len(record['content_camel'])


def test_multi_byte_characters_are_not_broken():
    record = _record_with_content('文档搜索 ' * 5000)
    fitted = fit_record_to_size(record)

    assert record_size_bytes(fitted) <= MAX_RECORD_SIZE_BYTES
    fitted['content'].encode('utf-8')  # decodable, no partial character
    assert not fitted['content'].endswith('\ufffd')


def test_hierarchy_is_trimmed_when_it_is_the_biggest_attribute():
    hierarchy = {'lvl0': 'h' * 20000, 'lvl1': None, 'lvl2': None,
                 'lvl3': None, 'lvl4': None, 'lvl5': None, 'lvl6': None}
    record = _record_with_content(
        'small content',
        hierarchy=hierarchy,
        hierarchy_camel=dict(hierarchy))
    fitted = fit_record_to_size(record)

    assert record_size_bytes(fitted) <= MAX_RECORD_SIZE_BYTES
    assert len(fitted['hierarchy']['lvl0']) < 20000


def test_truncate_utf8_keeps_whole_characters():
    assert truncate_utf8('abc', 10) == 'abc'
    assert truncate_utf8('abc', 2) == 'ab'
    assert truncate_utf8('abc', 0) == ''
    # 'é' is 2 bytes in UTF-8, cutting in the middle drops it entirely.
    assert truncate_utf8('éé', 3) == 'é'


def test_oversized_record_is_split_into_searchable_chunks():
    content = ('DocSearch indexes documentation pages. ' * 600).strip()
    record = _record_with_content(content)
    chunks = split_record(record)

    assert len(chunks) > 1
    assert all(record_size_bytes(chunk) <= MAX_RECORD_SIZE_BYTES
               for chunk in chunks)
    # The whole text is indexed: no content is dropped.
    assert ''.join(chunk['content'] for chunk in chunks) == content
    assert ''.join(chunk['content_camel'] for chunk in chunks) == content
    # Chunks point to the same page and are told apart by their objectID.
    assert {chunk['url'] for chunk in chunks} == {record['url']}
    object_ids = [chunk['objectID'] for chunk in chunks]
    assert len(set(object_ids)) == len(object_ids)
    assert object_ids[0] == record['objectID']
    assert object_ids[1] == '{}-1'.format(record['objectID'])
    # The hierarchy is kept so search results stay self-describing.
    assert all(chunk['hierarchy'] == record['hierarchy'] for chunk in chunks)


def test_split_record_is_stable_and_idempotent():
    record = _record_with_content('word ' * 6000)

    first = split_record(record)
    second = split_record(record)

    assert first == second
    for chunk in first:
        assert split_record(chunk) == [chunk]


def test_split_record_returns_small_records_unchanged():
    record = _record_with_content('small content')
    assert split_record(record) == [record]
    assert split_record(record)[0] is record


def test_split_record_trims_non_string_content_instead_of_splitting():
    record = _record_with_content(
        'x' * 1, extra_attributes={'text': 'y' * 50000})
    record['content'] = None

    records = split_record(record)

    assert len(records) == 1
    assert record_size_bytes(records[0]) <= MAX_RECORD_SIZE_BYTES


def test_split_record_keeps_multi_byte_content_searchable():
    content = '文档搜索 ' * 4000
    record = _record_with_content(content)
    chunks = split_record(record)

    assert len(chunks) > 1
    assert all(record_size_bytes(chunk) <= MAX_RECORD_SIZE_BYTES
               for chunk in chunks)
    assert ''.join(chunk['content'] for chunk in chunks) == content
    assert not any(chunk['content'].endswith('\ufffd')
                   for chunk in chunks)


def test_split_text_prefers_word_boundaries():
    text = ' '.join(['word'] * 1000)
    chunks = split_text(text, 100)

    assert all(len(chunk) <= 100 for chunk in chunks)
    assert all(chunk.split() == ['word'] * len(chunk.split())
               for chunk in chunks)
    assert ''.join(chunks) == text


def test_split_text_cuts_long_words_that_do_not_fit():
    chunks = split_text('a' * 250, 100)

    assert all(len(chunk) <= 100 for chunk in chunks)
    assert ''.join(chunks) == 'a' * 250
