import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import call, patch

from src.clients import MissingArchivalObjectError
from src.mergers import (ArchivalObjectMerger, ArrangementMapMerger,
                         BaseMerger, MergeError, ResourceMerger)

DEFAULT_CONFIG = {
    "AS_BASEURL": "https://as.rockarch.org/api",
    "AS_USERNAME": "admin",
    "AS_PASSWORD": "admin",
    "CARTOGRAPHER_BASEURL": "https://cartographer.rockarch.org",
    "CARTOGRAPHER_HEALTH_CHECK_PATH": "/status",
    "SNS_TOPIC": "sns-topic"
}


def json_from_file(filepath):
    with open(Path('tests', 'fixtures', filepath)) as df:
        data = json.load(df)
    return data


class BaseMergerTests(TestCase):

    @patch('src.clients.ArchivesSpaceClient.__init__')
    @patch('src.clients.CartographerClient.__init__')
    def get_merger(self, mock_cartographer, mock_as):
        """Helper to initialize merger."""
        mock_cartographer.return_value = None
        mock_as.return_value = None
        return BaseMerger(DEFAULT_CONFIG)

    @patch('src.clients.ArchivesSpaceClient.__init__')
    @patch('src.clients.CartographerClient.__init__')
    def test_init(self, mock_cartographer_client, mock_archivesspace_client):
        """Test client initialization called as expected."""
        mock_cartographer_client.return_value = None
        mock_archivesspace_client.return_value = None
        BaseMerger(DEFAULT_CONFIG)
        mock_cartographer_client.assert_called_once_with("https://cartographer.rockarch.org")
        mock_archivesspace_client.assert_called_once_with("https://as.rockarch.org/api", "admin", "admin")

    @patch('src.mergers.BaseMerger.get_identifier')
    @patch('src.mergers.BaseMerger.get_target_object_type')
    @patch('src.mergers.BaseMerger.get_additional_data')
    @patch('src.mergers.BaseMerger.combine_data')
    def test_merge(self, mock_combine_data, mock_additional_data, mock_target_object_type, mock_identifier):
        """Test merge methods called with expected args."""
        obj = {"uri": "12345"}
        identifier = "12345"
        object_type = "archival_object"
        combined_data = {"foo": "bar"}
        mock_identifier.return_value = identifier
        mock_target_object_type.return_value = object_type
        mock_additional_data.return_value = None
        mock_combine_data.return_value = combined_data

        merger = self.get_merger()
        output = merger.merge(obj)

        self.assertEqual(output, (combined_data, object_type))
        mock_identifier.assert_called_once_with(obj)
        mock_target_object_type.assert_called_once_with(obj)
        mock_additional_data.asssert_called_once_with(obj, object_type)
        mock_combine_data.assert_called_once_with(obj, None)

    @patch('src.mergers.BaseMerger.get_identifier')
    @patch('src.mergers.BaseMerger.get_target_object_type')
    def test_merge_exceptions(self, mock_object_type, mock_identifier):
        """Ensure exceptions are handled correctly."""
        mock_identifier.return_value = "12345"
        mock_object_type.side_effect = Exception("foo")
        merger = self.get_merger()
        with self.assertRaises(MergeError):
            merger.merge({})

        """Missing archival objects should return None"""
        mock_identifier.side_effect = MissingArchivalObjectError("foo")
        output = merger.merge({})
        self.assertEqual(output, None)

    def test_get_identifier(self):
        """Test identifiers correctly parsed."""
        merger = self.get_merger()
        for input, expected in [
                ({"uri": "12345", "ref": "54321"}, "12345"),
                ({"ref": "54321"}, "54321")]:
            output = merger.get_identifier(input)
            self.assertEqual(output, expected)

    @patch('src.mergers.BaseMerger.add_group')
    def test_combine_data(self, mock_add_group):
        obj = {}
        additional_data = {"baz": "buzz"}
        mock_add_group.return_value = {"foo": "bar"}
        merger = self.get_merger()
        output = merger.combine_data(obj, additional_data)
        self.assertEqual(output, {"group": {"foo": "bar"}})
        mock_add_group.assert_called_once_with(obj)

    @patch('src.clients.ArchivesSpaceClient.has_children')
    def test_get_target_object_type(self, mock_has_children):
        """Test object type correctly parsed."""
        merger = self.get_merger()
        for input, expected, has_children in [
                ({"jsonmodel_type": "resource"}, "resource", False),
                ({
                    "jsonmodel_type": "archival_object",
                    "uri": "/repositories/2/archival_objects/1"},
                    "archival_object", False),
                ({
                    "jsonmodel_type": "archival_object",
                    "uri": "/repositories/2/archival_objects/1"},
                    "archival_object_collection", True)]:
            mock_has_children.return_value = has_children
            output = merger.get_target_object_type(input)
            self.assertEqual(output, expected)

    def test_combine_references(self):
        """Test references correctly combined."""
        input = json_from_file('references/source.json')
        expected = json_from_file('references/output.json')
        merger = self.get_merger()
        output = merger.combine_references(input)
        self.assertEqual(output, expected)

    @patch('src.clients.ArchivesSpaceClient.resource_data')
    @patch('src.mergers.BaseMerger.combine_references')
    def test_add_group(self, mock_combine, mock_resource_data):
        merger = self.get_merger()

        """No ancestors on source object"""
        source_data = {
            "jsonmodel_type": "archival_object",
            "ref": "/repositories/2/archival_objects/1",
            "dates": [{"foo": "bar"}],
            "title": "source data title",
            "linked_agents": [{"title": "creator name", "role": "creator"}]}
        mock_combine.return_value = source_data
        output = merger.add_group(source_data)
        self.assertEqual(output, {
            'identifier': '/repositories/2/archival_objects/1',
            'creators': [{'title': 'creator name', 'role': 'creator'}],
            'dates': [{'foo': 'bar'}],
            'title': 'source data title'})
        mock_resource_data.assert_not_called()
        mock_combine.assert_called_once_with(source_data)

        """Ancestors on source object"""
        ancestor_uri = "/repositories/2/archival_objects/1"
        source_data = {
            "jsonmodel_type": "archival_object",
            "ref": "/repositories/2/archival_objects/1",
            "dates": [{"foo": "bar"}],
            "title": "source data title",
            "linked_agents": [{"title": "creator name", "role": "creator"}],
            "ancestors": [{"ref": ancestor_uri}]}
        mock_combine.return_value = source_data
        output = merger.add_group(source_data)
        self.assertEqual(output, {
            'identifier': '/repositories/2/archival_objects/1',
            'creators': [{'title': 'creator name', 'role': 'creator'}],
            'dates': [{'foo': 'bar'}],
            'title': 'source data title'})
        mock_resource_data.assert_called_once_with(ancestor_uri)

        """Agent object"""
        source_data = {
            "jsonmodel_type": "agent_person",
            "uri": "/agents/people/1",
            "dates_of_existence": [{"foo": "bar"}],
            "title": "source data title"}
        mock_combine.return_value = source_data
        output = merger.add_group(source_data)
        self.assertEqual(output, {
            'identifier': '/agents/people/1',
            'creators': [{
                'ref': '/agents/people/1',
                'role': 'creator',
                'type': 'agent_person',
                'title': 'source data title'}],
            'dates': [{'foo': 'bar'}],
            'title': 'source data title'})


class ArchivalObjectMergerTests(TestCase):

    @patch('src.clients.ArchivesSpaceClient.__init__')
    @patch('src.clients.CartographerClient.__init__')
    def setUp(self, mock_cartographer, mock_as):
        """Helper to initialize merger."""
        mock_cartographer.return_value = None
        mock_as.return_value = None
        self.merger = ArchivalObjectMerger(DEFAULT_CONFIG)

    @patch('src.mergers.ArchivalObjectMerger.get_cartographer_data')
    @patch('src.mergers.ArchivalObjectMerger.get_archivesspace_data')
    def test_get_additional_data(self, mock_as_data, mock_cartographer_data):
        """Asserts methods are called with expected args."""
        obj = {"baz": "buzz"}
        mock_as_data.return_value = {"linked_agents": [{"foo": "bar"}]}
        mock_cartographer_data.return_value = {"ancestors": [{"foo": "bar"}]}

        output = self.merger.get_additional_data(obj, 'archival_object')

        self.assertEqual(output, {"linked_agents": [{"foo": "bar"}], "ancestors": [{"foo": "bar"}]})
        mock_as_data.assert_called_once_with(obj, 'archival_object')
        mock_cartographer_data.assert_called_once_with(obj)

    @patch('src.clients.CartographerClient.resolve_component')
    @patch('src.clients.CartographerClient.handle_reference')
    def test_get_cartographer_data(self, mock_reference, mock_component):
        """Test data fetched from Cartographer as expected"""
        resource_ref = "repositories/2/resources/1"
        obj = {"resource": {"ref": resource_ref}}
        # No Cartographer component found
        mock_component.return_value = None
        output = self.merger.get_cartographer_data(obj)
        self.assertEqual(output, {"ancestors": []})
        mock_component.assert_called_once_with(resource_ref)

        # Cartographer component found
        mock_component.return_value = {"ancestors": [{}]}
        mock_reference.return_value = {"foo": "bar"}
        output = self.merger.get_cartographer_data(obj)
        self.assertEqual(output, {"ancestors": [{"foo": "bar"}]})

    @patch('src.mergers.closest_parent_value')
    def test_get_language_data(self, mock_closest):
        """Tests language and lang_materials are correctly parsed."""
        mock_closest.return_value = "eng"
        for obj, expected in [
                ({"lang_materials": "eng"}, {}),
                ({"lang_materials": ""}, {"lang_materials": "eng"}),
                ({"language": "eng"}, {"language": "eng"})]:
            output = self.merger.get_language_data(obj, {})
            self.assertEqual(output, expected)

    def test_parse_instances(self):
        """Test instances parsed as expected"""
        for input_path, output_path in [
                ('instances/source_subcontainer.json', 'instances/output_subcontainer.json'),
                ('instances/source_no_subcontainer.json', 'instances/output_no_subcontainer.json')]:
            input = json_from_file(input_path)
            expected = json_from_file(output_path)
            output = self.merger.parse_instances(input)
            self.assertEqual(output, expected)

        with self.assertRaises(Exception) as err:
            self.merger.parse_instances([{"sub_container": "foo"}])
        self.assertTrue(str(err.exception).startswith("Error parsing instances: "))

    @patch('src.clients.ArchivesSpaceClient.tree_node')
    @patch('src.clients.ArchivesSpaceClient.tree_root')
    @patch('src.clients.ArchivesSpaceClient.objects_before')
    @patch('src.clients.CartographerClient.resolve_component')
    @patch('src.clients.CartographerClient.objects_before')
    def test_get_position(self, mock_cartographer_objects_before, mock_cartographer_resolve, mock_as_objects_before, mock_as_tree_root, mock_as_tree_node):
        """Test position calculated correctly."""
        ancestor_ref = "repositories/2/archival_objects/1"
        resource_ref = "repositories/2/resources/1"
        cartographer_ref = "/api/components/1"
        obj = {"resource": {"ref": resource_ref}, "ancestors": [{"ref": ancestor_ref}, {"ref": resource_ref}]}
        mock_as_tree_node.return_value = "tree_node"
        mock_as_tree_root.return_value = "tree_root"
        mock_as_objects_before.return_value = 5
        mock_cartographer_resolve.return_value = {"ref": cartographer_ref}
        mock_cartographer_objects_before.return_value = 5

        output = self.merger.get_position(obj)

        self.assertEqual(output, 15)
        mock_as_tree_node.assert_called_once_with(resource_ref, ancestor_ref)
        mock_as_tree_root.assert_called_once_with(resource_ref)
        mock_as_objects_before.assert_has_calls([
            call(obj, "tree_node", resource_ref, ancestor_ref),
            call(obj["ancestors"][-2], "tree_root", resource_ref)])
        mock_cartographer_resolve.assert_called_once_with(resource_ref)
        mock_cartographer_objects_before.assert_called_once_with(cartographer_ref)

    @patch('src.mergers.closest_parent_value')
    @patch('src.mergers.closest_creators')
    @patch('src.mergers.ArchivalObjectMerger.get_language_data')
    @patch('src.mergers.ArchivalObjectMerger.parse_instances')
    @patch('src.mergers.ArchivalObjectMerger.get_position')
    def test_get_archivesspace_data(self, mock_position, mock_instances, mock_language, mock_creators, mock_parent):
        mock_position.return_value = 15
        mock_instances.return_value = [{"extent_type": "box", "number": 1}]
        mock_language.return_value = {"language": "eng"}
        mock_creators.return_value = [{"name": "creator"}]
        mock_parent.side_effect = [
            [{"begin": "2021-01", "end": "2023-12", "expression": "2021-2023"}],
            [{"begin": "2021-01", "end": "2023-12", "expression": "2021-2023"}],
            {"extent_type": "folder"}]

        obj = {"dates": [{"foo": "bar"}], "extents": [{"baz": "buzz"}]}
        output = self.merger.get_archivesspace_data(obj, 'archival_object')
        self.assertEqual(output, {'linked_agents': [], 'language': 'eng', 'position': 15})

        obj = {"instances": []}
        output = self.merger.get_archivesspace_data(obj, 'archival_object')
        self.assertEqual(
            output,
            {
                'linked_agents': [],
                'dates': [{'begin': '2021-01', 'end': '2023-12', 'expression': '2021-2023'}],
                'language': 'eng',
                'extents': [{'extent_type': 'box', 'number': 1}],
                'position': 15})

        obj = {"instances": []}
        mock_instances.return_value = None
        output = self.merger.get_archivesspace_data(obj, 'archival_object_collection')
        self.assertEqual(
            output,
            {
                'linked_agents': [{'name': 'creator'}],
                'dates': [{'begin': '2021-01', 'end': '2023-12', 'expression': '2021-2023'}],
                'language': 'eng',
                'extents': {'extent_type': 'folder'},
                'position': 15})

    @patch('src.mergers.ArchivalObjectMerger.add_group')
    def test_combine_data(self, mock_add_group):
        mock_add_group.return_value = {"foo": "bar"}
        obj = {
            "instances": [{
                "subcontainer": {"top_container": {"_resolved": {"foo": "bar"}}},
                "digital_object": {"_resolved": {"baz": "buzz"}}}],
            "linked_agents": [{"foo": "bar"}],
            "title": "original title"}
        additional_data = {"linked_agents": [{"baz": "buzz"}], "title": "new title"}
        expected = {
            'instances': [{
                'subcontainer': {'top_container': {'_resolved': {'foo': 'bar'}}},
                'digital_object': {'baz': 'buzz'}}],
            'linked_agents': [{'foo': 'bar'}, {'baz': 'buzz'}],
            'title': 'new title',
            'group': {'foo': 'bar'}}

        output = self.merger.combine_data(obj, additional_data)
        self.assertEqual(output, expected)


class ArrangementMapMergerTests(TestCase):

    @patch('src.clients.ArchivesSpaceClient.__init__')
    @patch('src.clients.CartographerClient.__init__')
    def setUp(self, mock_cartographer, mock_as):
        """Helper to initialize merger."""
        mock_cartographer.return_value = None
        mock_as.return_value = None
        self.merger = ArrangementMapMerger(DEFAULT_CONFIG)

    def test_get_target_object_type(self):
        self.assertEqual(self.merger.get_target_object_type({}), 'resource')

    @patch('src.clients.ArchivesSpaceClient.resource_data')
    def test_get_additional_data(self, mock_resource):
        mock_resource.return_value = {"foo": "bar"}
        output = self.merger.get_additional_data({"archivesspace_uri": "/repositories/2/resources/1"}, {})
        self.assertEqual(output, {"foo": "bar"})
        mock_resource.assert_called_once_with("/repositories/2/resources/1")

    @patch('src.clients.CartographerClient.handle_reference')
    @patch('src.mergers.BaseMerger.add_group')
    @patch('src.mergers.BaseMerger.combine_references')
    def test_combine_data(self, mock_combine_references, mock_add_group, mock_handle_reference):
        obj = {"ancestors": [{"foo": "bar"}, {"baz": "buzz"}], "order": 2}
        mock_handle_reference.return_value = {"foo": "bar"}
        mock_add_group.return_value = {"biz": "baz"}
        mock_combine_references.return_value = {"uri": "12345"}

        output = self.merger.combine_data(obj, {})
        self.assertEqual(output, {"uri": "12345"})
        mock_handle_reference.assert_has_calls([call({"foo": "bar"}), call({"baz": "buzz"})])
        mock_combine_references.assert_called_once_with({
            'ancestors': [{'foo': 'bar'}, {'foo': 'bar'}],
            'position': 2,
            'group': {'biz': 'baz'}})


class ResourceMergerTests(TestCase):

    @patch('src.clients.ArchivesSpaceClient.__init__')
    @patch('src.clients.CartographerClient.__init__')
    def setUp(self, mock_cartographer, mock_as):
        """Helper to initialize merger."""
        mock_cartographer.return_value = None
        mock_as.return_value = None
        self.merger = ResourceMerger(DEFAULT_CONFIG)

    @patch('src.mergers.ResourceMerger.get_cartographer_data')
    def test_get_additional_data(self, mock_cartographer_data):
        mock_cartographer_data.return_value = {"foo": "bar"}
        output = self.merger.get_additional_data({}, 'resource')
        self.assertEqual(output, {"foo": "bar"})
        mock_cartographer_data.assert_called_once_with({})

    @patch('src.clients.CartographerClient.resolve_component')
    @patch('src.clients.CartographerClient.objects_before')
    @patch('src.clients.CartographerClient.handle_reference')
    def test_get_cartographer_data(self, mock_handle_reference, mock_objects_before, mock_resolve_component):
        obj = {"uri": "/repositories/2/resources/1"}
        mock_resolve_component.return_value = None
        output = self.merger.get_cartographer_data(obj)
        self.assertEqual(output, {'ancestors': []})
        mock_resolve_component.assert_called_once_with(obj['uri'])
        mock_objects_before.assert_not_called()
        mock_handle_reference.assert_not_called()

        mock_resolve_component.return_value = {"ref": "/api/components/1", "ancestors": [{"foo": "bar"}, {"baz": "buzz"}]}
        mock_objects_before.return_value = 2
        mock_handle_reference.return_value = {"uri": "1234"}
        output = self.merger.get_cartographer_data(obj)
        self.assertEqual(output, {'ancestors': [{'uri': '1234'}, {'uri': '1234'}], 'order': 2})
        mock_objects_before.assert_called_once_with("/api/components/1")
        mock_handle_reference.assert_has_calls([call({"foo": "bar"}), call({"baz": "buzz"})])

    @patch('src.mergers.BaseMerger.add_group')
    @patch('src.mergers.BaseMerger.combine_references')
    def test_combine_data(self, mock_combine_references, mock_add_group):
        additional_data = {"ancestors": [{"foo": "bar"}], "order": 2}
        mock_add_group.return_value = {"foo": "bar"}
        mock_combine_references.return_value = {"baz": "buzz"}
        output = self.merger.combine_data({}, additional_data)
        self.assertEqual(output, {"baz": "buzz"})
        mock_combine_references.assert_called_once_with({
            'ancestors': [{'foo': 'bar'}],
            'position': 2,
            'group': {'foo': 'bar'}})
