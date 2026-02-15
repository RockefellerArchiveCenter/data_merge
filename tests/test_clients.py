from unittest import TestCase
from unittest.mock import call, patch

from electronbonder.client import ElectronBond

from src.clients import (ArchivesSpaceClient, CartographerClient,
                         MissingArchivalObjectError)


class MockResponse(object):
    """Class used to mock HTTP responses"""

    def __init__(self, json_data, status_code, **kwargs):
        """Sets data, status code, and any other data passed in."""
        self.json_data = json_data
        self.status_code = status_code
        self.text = "v4.0.0"
        for k in kwargs:
            setattr(self, k, kwargs[k])

    def json(self):
        """Mocks the json method of an HTTP response"""
        return self.json_data

    def raise_for_status(self):
        pass


class ArchivesSpaceClientTests(TestCase):

    @patch('asnake.client.ASnakeClient.get')
    @patch('asnake.client.ASnakeClient.authorize')
    def setUp(self, mock_authorize, mock_get):
        mock_get.return_value = MockResponse({}, 200)
        self.client = ArchivesSpaceClient("https://as.rockarch.org/api", "admin", "admin")

    @patch('asnake.client.ASnakeClient.get')
    def test_has_children(self, mock_get):
        uri = "/repositories/2/archival_objects/1"

        """Missing archival object"""
        mock_get.return_value = MockResponse({}, 404)
        with self.assertRaises(MissingArchivalObjectError) as err:
            self.client.has_children(uri)
        self.assertTrue(uri in str(err.exception))

        """Archival object with children"""
        mock_get.reset_mock()
        mock_get.side_effect = [
            MockResponse({"resource": {"ref": "/repositories/2/resources/1"}}, 200),
            MockResponse({"child_count": 1}, 200)]
        self.assertTrue(self.client.has_children(uri))
        mock_get.assert_has_calls([call(uri), call(f"/repositories/2/resources/1/tree/node?node_uri={uri}")])

        """Archival object without children"""
        mock_get.reset_mock()
        mock_get.side_effect = [
            MockResponse({"resource": {"ref": "/repositories/2/resources/1"}}, 200),
            MockResponse({"child_count": 0}, 200)]
        self.assertFalse(self.client.has_children(uri))

    @patch('asnake.client.ASnakeClient.get')
    def test_tree_root(self, mock_get):
        uri = "/repositories/2/resources/1"
        mock_get.return_value = MockResponse({"tree": "root"}, 200)
        output = self.client.tree_root(uri)
        self.assertEqual(output, {"tree": "root"})
        mock_get.assert_called_once_with('/repositories/2/resources/1/tree/root')

    @patch('asnake.client.ASnakeClient.get')
    def test_tree_node(self, mock_get):
        resource_uri = "/repositories/2/resources/1"
        node_uri = "/repositories/2/archival_objects/1"
        mock_get.return_value = MockResponse({"tree": "node"}, 200)
        output = self.client.tree_node(resource_uri, node_uri)
        self.assertEqual(output, {"tree": "node"})
        mock_get.assert_called_once_with(
            '/repositories/2/resources/1/tree/node?node_uri=/repositories/2/archival_objects/1')

    @patch('asnake.client.ASnakeClient.get')
    def test_objects_within(self, mock_get):
        """Empty URI list should return 0"""
        self.assertEqual(self.client.objects_within([]), 0)

        """Exception when searching"""
        uri_list = ["/repositories/2/archival_objects/1", "/repositories/2/archival_objects/2"]
        mock_get.return_value = MockResponse({}, 500)
        with self.assertRaises(Exception) as err:
            self.client.objects_within(uri_list)
        self.assertTrue(str(err.exception).startswith('Error fetching child counts for URI'))
        self.assertTrue(all([u in str(err.exception) for u in uri_list]))

        """Count returned as expected"""
        mock_get.return_value = MockResponse({"total_hits": 2}, 200)
        output = self.client.objects_within(uri_list)
        self.assertEqual(output, 2)
        mock_get.assert_called_with(
            'search?q=ancestors:"/repositories/2/archival_objects/1" ancestors:"/repositories/2/archival_objects/2"&filter_query[]=publish:true&page=1&fields[]=uri&type[]=archival_object&page_size=1')

    @patch('asnake.client.ASnakeClient.get')
    @patch('src.clients.ArchivesSpaceClient.objects_within')
    def test_objects_before(self, mock_within, mock_get):
        target_node = {"position": 4}
        initial_node = {"waypoints": 2, "waypoint_size": 5}
        resource_uri = "/repositories/2/resources/1"
        mock_get.return_value = MockResponse([{"position": 0, "uri": "/repositories/2/archival_objects/2"}], 200)
        mock_within.return_value = 2

        """No waypoints"""
        self.assertEqual(self.client.objects_before(target_node, {"waypoints": 0}, resource_uri), 0)

        """No Parent URI"""
        output = self.client.objects_before(target_node, initial_node, resource_uri)
        self.assertEqual(output, 4)
        mock_within.assert_called_once_with(["/repositories/2/archival_objects/2"])
        mock_get.assert_called_once_with('/repositories/2/resources/1/tree/waypoint?offset=0')

        """Parent URI"""
        mock_within.reset_mock()
        mock_get.reset_mock()
        target_node = {"_resolved": {"position": 10}}  # Position in resolved data
        output = self.client.objects_before(target_node, initial_node, resource_uri, "/repositories/2/archival_objects/3")
        self.assertEqual(output, 8)
        mock_within.assert_has_calls([
            call(["/repositories/2/archival_objects/2"]),
            call(["/repositories/2/archival_objects/2"])])
        mock_get.assert_has_calls([
            call('/repositories/2/resources/1/tree/waypoint?offset=0&parent_node=/repositories/2/archival_objects/3'),
            call('/repositories/2/resources/1/tree/waypoint?offset=1&parent_node=/repositories/2/archival_objects/3')])

    @patch('asnake.client.ASnakeClient.get')
    def test_resource_data(self, mock_get):
        uri = "/repositories/2/resources/1"
        mock_get.return_value = MockResponse({"uri": uri}, 200)
        output = self.client.resource_data(uri)
        self.assertEqual(output, {"uri": uri})
        mock_get.assert_called_once_with(uri, params={"resolve": ["subjects", "linked_agents"]})


class CartographerClientTests(TestCase):

    def setUp(self):
        self.client = CartographerClient("https://cartographer.rockarch.org")

    def test_init(self):
        self.assertIsInstance(self.client.client, ElectronBond)

    def test_handle_reference(self):
        reference = {"archivesspace_uri": "/repositories/2/resources/1"}
        output = self.client.handle_reference(reference)
        self.assertEqual(output, {"ref": "/repositories/2/resources/1", "type": "collection"})

    @patch('electronbonder.client.ElectronBond.get')
    def test_resolve_component(self, mock_get):
        mock_get.return_value = MockResponse({"count": 1, "results": [{"foo": "bar"}]}, 200)
        uri = "/api/components/1"
        output = self.client.resolve_component(uri)
        self.assertEqual(output, {"foo": "bar"})
        mock_get.assert_called_once_with("/api/find-by-uri/", params={"uri": uri})

    @patch('electronbonder.client.ElectronBond.get')
    def test_objects_before(self, mock_get):
        mock_get.return_value = MockResponse({"count": 2}, 200)
        uri = "/api/components/1"
        output = self.client.objects_before(uri)
        self.assertEqual(output, 2)
        mock_get.assert_called_once_with('/api/components/1/objects_before/')
