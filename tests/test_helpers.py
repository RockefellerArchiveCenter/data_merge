from unittest.mock import patch

from src.helpers import (closest_creators, closest_parent_value, get_ancestors,
                         get_date_string, indicator_to_integer, list_chunks)


def test_list_chunks():
    initial_list = [1, 2, 3, 4, 5, 6, 7]
    output = list(list_chunks(initial_list, 3))
    assert output == [[1, 2, 3], [4, 5, 6], [7]]


def test_indicator_to_integer():
    for input, expected in [('23', 23), ('23b', 23), ('B', 1), ('Be', 1)]:
        output = indicator_to_integer(input)
        assert output == expected


def test_get_ancestors():
    obj = {'ancestors': [
        {'_resolved': {'uri': '/repositories/2/archival_objects/1'}},
        {'_resolved': {'uri': '/repositories/2/archival_objects/2'}},
        {'_resolved': {'uri': '/repositories/2/resources/1'}}]}
    output = get_ancestors(obj)
    assert list(output) == [
        {'uri': '/repositories/2/archival_objects/1'},
        {'uri': '/repositories/2/archival_objects/2'},
        {'uri': '/repositories/2/resources/1'}]


@patch('src.helpers.get_ancestors')
def test_closest_parent_value(mock_ancestors):
    mock_ancestors.return_value = [
        {},
        {'uri': {}},
        {'uri': []},
        {'uri': ''},
        {'uri': '/repositories/2/archival_objects/1'}]
    output = closest_parent_value({}, 'uri')
    assert output == '/repositories/2/archival_objects/1'


@patch('src.helpers.get_ancestors')
def test_closest_creators(mock_ancestors):
    mock_ancestors.return_value = [
        {'linked_agents': [
            {'name': 'Scrooge McDuck', 'role': 'creator'},
            {'name': 'Daffy Duck', 'role': 'subject'}]}]
    output = closest_creators({})
    assert output == [{'name': 'Scrooge McDuck', 'role': 'creator'}]

    mock_ancestors.return_value = [{'linked_agents': [{'name': 'Daffy Duck', 'role': 'subject'}]}]
    output = closest_creators({})
    assert output == []

    mock_ancestors.return_value = []
    output = closest_creators({})
    assert output == []


def test_get_date_string():
    for input, expected in [
            ([], ''),
            ([{'expression': 'December 1990 - February 1991', 'begin': '1990', 'end': '1991'}], 'December 1990 - February 1991'),
            ([{'begin': '1990', 'end': '1991'}, {'begin': '1995', 'end': '1996'}], '1990-1991, 1995-1996'),
            ([{'begin': '1991'}], '1991')]:
        output = get_date_string(input)
        assert output == expected
