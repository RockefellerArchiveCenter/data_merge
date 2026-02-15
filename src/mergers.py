from .clients import (ArchivesSpaceClient, CartographerClient,
                      MissingArchivalObjectError)
from .helpers import (closest_creators, closest_parent_value, get_date_string,
                      indicator_to_integer)


class MergeError(Exception):
    pass


class BaseMerger:
    """Base merger class."""

    def __init__(self, config):
        self.as_client = ArchivesSpaceClient(
            config['AS_BASEURL'],
            config['AS_USERNAME'],
            config['AS_PASSWORD'])
        self.cartographer_client = CartographerClient(config['CARTOGRAPHER_BASEURL'])

    def merge(self, source_data):
        """Main merge function.

        Fetches and merges additional data from secondary data sources, then
        delivers merged data to the configured URL."""
        try:
            identifier = self.get_identifier(source_data)
            target_object_type = self.get_target_object_type(source_data)
            additional_data = self.get_additional_data(source_data, target_object_type)
            return self.combine_data(source_data, additional_data), target_object_type
        except MissingArchivalObjectError:
            pass  # Archival object was updated and then immediately deleted
        except Exception as e:
            raise MergeError(f"Error merging {identifier}: {e}")

    def get_identifier(self, source_data):
        """Returns the identifier for the source_data."""
        try:
            identifier = source_data["uri"]
        except KeyError:
            identifier = source_data["ref"]
        return identifier

    def get_additional_data(self, source_data, object_type):
        pass

    def combine_data(self, source_data, additional_data):
        return self.add_group(source_data)

    def get_target_object_type(self, data):
        """Returns object type.

        Archival objects that have children are mapped differently from those
        without.
        """
        if data.get("jsonmodel_type") == "archival_object":
            if self.as_client.has_children(data["uri"]):
                return "archival_object_collection"
        return data.get("jsonmodel_type")

    # TODO does it make sense to just return the references?
    def combine_references(self, source_data):
        """Adds type and title fields to references, then removes unneeded resolved objects."""
        for key in ["ancestors", "children", "subjects", "linked_agents"]:
            for obj in source_data.get(key, []):
                if obj.get("_resolved"):
                    type = "collection"
                    if key == "subjects":
                        type = obj["_resolved"]["terms"][0]["term_type"]
                    elif key == "linked_agents":
                        type = obj["_resolved"]["agent_type"]
                    if obj["_resolved"].get("subjects"):
                        obj["subjects"] = self.combine_references(obj["_resolved"])["subjects"]
                    obj["type"] = type
                    obj["title"] = obj["_resolved"].get("title", obj["_resolved"].get("display_string"))
                    obj["dates"] = get_date_string(obj["_resolved"].get("dates", []))
                    del obj["_resolved"]
        return source_data

    # TODO this is a little counter intuitive; could just return the group rather than returning the whole object.
    def add_group(self, source_data):
        """Adds group object, with data about the highest-level collection containing this object."""

        top_ancestor = source_data
        if source_data.get("ancestors"):
            last_ancestor = source_data["ancestors"][-1]
            top_ancestor = last_ancestor["_resolved"] if last_ancestor.get("_resolved") else self.as_client.resource_data(
                last_ancestor.get("archivesspace_uri", last_ancestor.get("ref")))

        group_obj = self.combine_references(top_ancestor)

        creators = [a for a in group_obj.get("linked_agents", []) if a["role"] == "creator"]
        if source_data["jsonmodel_type"].startswith("agent_"):
            creators = [{
                "ref": source_data["uri"],
                "role": "creator",
                "type": source_data["jsonmodel_type"],
                "title": source_data["title"]}]

        source_data["group"] = {
            "identifier": group_obj.get("ref", group_obj.get("uri")),
            "creators": creators,
            "dates": group_obj.get("dates", group_obj.get("dates_of_existence", [])),
            "title": group_obj.get("title"),
        }
        return source_data


class ArchivalObjectMerger(BaseMerger):

    def get_additional_data(self, source_data, object_type):
        """Fetches additional data from ArchivesSpace and Cartographer.

        Args:
            source_data (dict): source data (an ArchivesSpace archival object record).
            object_type (str): the source object type, either `archival_object`
                or `archival_object_collection`.

        Returns:
            dict: a dictionary of data to be merged.
        """
        data = {"ancestors": [], "linked_agents": []}
        data.update(self.get_cartographer_data(source_data))
        data.update(self.get_archivesspace_data(source_data, object_type))
        return data

    def get_cartographer_data(self, source_data):
        """Gets ancestors, if any, from the archival object's resource record in Cartographer."""
        data = {"ancestors": []}
        result = self.cartographer_client.resolve_component(source_data["resource"]["ref"])
        if result:
            for a in result.get("ancestors", []):
                data["ancestors"].append(self.cartographer_client.handle_reference(a))
        return data

    def get_language_data(self, source_data, data):
        """Gets language data from ArchivesSpace.

        This logic accomodates ArchivesSpace API changes between 2.6 and 2.7.
        """
        if "lang_materials" in source_data:
            if source_data.get("lang_materials") in ["", [], {}]:
                data["lang_materials"] = closest_parent_value(source_data, "lang_materials")
        else:
            data["language"] = closest_parent_value(source_data, "language")
        return data

    def parse_instances(self, instances):
        """Attempts to parse extents from instances.

        Initially, child subcontainers are parsed to determine
        the extent number and extent type. If a child subcontainer does not
        exist, the parent container is parsed.
        """

        def append_to_list(extents, extent_type, extent_number):
            """Merges or appends extent objects to an extent list.

            Only operates over instances with a sub_container (i.e. skips
            digital object instances.

            Args:
                extents (list): a list of extents to update.
                extent_type (str): the extent type to add.
                extent_number (int): the extent number to add
            """
            matching_extents = [e for e in extents if e["extent_type"] == extent_type]
            if matching_extents:
                matching_extents[0]["number"] += extent_number
            else:
                extents.append({"extent_type": extent_type, "number": extent_number})
            return extents

        extents = []
        for instance in [i for i in instances if i.get("sub_container")]:
            try:
                sub_container_parseable = all(i_type in instance.get("sub_container", {}) for i_type in ["indicator_2", "type_2"])
                if sub_container_parseable:
                    number_list = [i.strip() for i in instance["sub_container"]["indicator_2"].split("-")]
                    range = sorted(map(indicator_to_integer, number_list))
                    extent_type = instance["sub_container"]["type_2"]
                    extent_number = range[-1] - range[0] + 1 if len(range) > 1 else 1
                else:
                    instance_type = instance["instance_type"].lower()
                    sub_container_type = instance["sub_container"]["top_container"]["_resolved"].get("type", "").lower()
                    extent_type = "{} {}".format(instance_type, sub_container_type) if sub_container_type != "box" else sub_container_type
                    extent_number = 1
                extents = append_to_list(extents, extent_type.strip(), extent_number)
            except Exception as e:
                raise Exception(f"Error parsing instances: {e}") from e
        return extents

    def get_position(self, source_data):
        """Gets the position of the object within the collection.

        This is calculated based on the sum of previous ancestors, previous top
        ancestors in ArchivesSpace, and previous ancestors in Cartographer.
        """

        previous_ancestors_count = 0
        for idx, ancestor in enumerate(source_data["ancestors"]):
            target_node = source_data["ancestors"][idx - 1] if idx > 0 else source_data
            if "resource" not in ancestor["ref"]:
                tree_node = self.as_client.tree_node(source_data["resource"]["ref"], ancestor["ref"])
                previous_ancestors_count += self.as_client.objects_before(
                    target_node,
                    tree_node,
                    source_data["resource"]["ref"],
                    ancestor["ref"])

        target_node = source_data["ancestors"][-2] if len(source_data["ancestors"]) > 1 else source_data
        tree_root = self.as_client.tree_root(source_data["resource"]["ref"])
        previous_top_ancestors_count = self.as_client.objects_before(
            target_node,
            tree_root,
            source_data["resource"]["ref"])

        cartographer_count = 0
        result = self.cartographer_client.resolve_component(source_data["resource"]["ref"])
        if result:
            cartographer_count = self.cartographer_client.objects_before(result['ref'])

        return sum([previous_ancestors_count, previous_top_ancestors_count, cartographer_count])

    def get_archivesspace_data(self, source_data, object_type):
        """Gets dates, languages, and extent from archival object's
        resource record in ArchivesSpace.
        """
        data = {"linked_agents": []}
        if source_data.get("dates") in ["", [], {}, None]:
            data["dates"] = closest_parent_value(source_data, "dates")
        data.update(self.get_language_data(source_data, data))
        if not source_data.get("extents"):
            extent_data = self.parse_instances(source_data["instances"])
            if object_type == "archival_object_collection" and not extent_data:
                extent_data = closest_parent_value(source_data, "extents")
            data["extents"] = extent_data
        if object_type == "archival_object_collection":
            data["linked_agents"] = closest_creators(source_data)
        data["position"] = self.get_position(source_data)
        return data

    def combine_data(self, source_data, additional_data):
        """Combines additional data with source data.

        Moves data from resolved objects to expected keys within main object.
        Removes resolved top_container data.
        Moves resolved digital object data to expected key in main object.
        """
        for k, v in additional_data.items():
            if isinstance(v, list):
                source_data[k] = source_data.get(k, []) + v
            else:
                source_data[k] = v
        for instance in source_data.get("instances", []):
            if instance.get("sub_container", {}).get("top_container", {}).get("_resolved"):
                del instance["sub_container"]["top_container"]["_resolved"]
            if instance.get("digital_object"):
                instance["digital_object"] = instance["digital_object"]["_resolved"]
        with_group = self.add_group(source_data)
        return self.combine_references(with_group)


class ArrangementMapMerger(BaseMerger):

    def get_target_object_type(self, data):
        return "resource"

    def get_additional_data(self, source_data, object_type):
        """Fetches the ArchivesSpace resource record referenced by the
        ArrangementMapComponent.

        Args:
            object (dict): source object (an ArrangementMapComponent).
            object_type (str): the source object type, `arrangement_map_component`.

        Returns:
            dict: a dictionary of data to be merged.
        """
        return self.as_client.resource_data(source_data["archivesspace_uri"])

    def combine_data(self, source_data, additional_data):
        """Adds Cartographer ancestors to ArchivesSpace resource record."""
        additional_data["ancestors"] = [self.cartographer_client.handle_reference(a) for a in source_data.get("ancestors", [])]
        additional_data["position"] = source_data["order"]
        additional_data = self.add_group(additional_data)
        return self.combine_references(additional_data)


class AgentMerger(BaseMerger):
    pass


class ResourceMerger(BaseMerger):

    def get_additional_data(self, source_data, object_type):
        """Gets additional data from Cartographer and ArchivesSpace.

        Args:
            object (dict): source object (an ArchivesSpace resource record).
            object_type (str): the source object type, always `resource`.

        Returns:
            dict: a dictionary of data to be merged.
        """
        return self.get_cartographer_data(source_data)

    def get_cartographer_data(self, source_data):
        """Returns ancestors (if any) for the resource record from Cartographer."""
        data = {"ancestors": []}
        result = self.cartographer_client.resolve_component(source_data["uri"])
        if result:
            data["order"] = self.cartographer_client.objects_before(result['ref'])
            for a in result.get("ancestors", []):
                data["ancestors"].append(self.cartographer_client.handle_reference(a))
        return data

    def combine_data(self, source_data, additional_data):
        """Combines existing ArchivesSpace data with Cartographer data.

        Adds Cartographer ancestors to object's `ancestors` key.
        """
        source_data["ancestors"] = additional_data["ancestors"]
        source_data["position"] = additional_data.get("order", 0) if additional_data else 0
        with_group = self.add_group(source_data)
        return self.combine_references(with_group)


class SubjectMerger(BaseMerger):
    pass
