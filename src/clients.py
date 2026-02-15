from asnake.aspace import ASpace
from electronbonder.client import ElectronBond

from .helpers import list_chunks


class MissingArchivalObjectError(Exception):
    pass


class ArchivesSpaceClient(object):

    def __init__(self, baseurl, username, passsword):
        self.client = ASpace(
            baseurl=baseurl,
            username=username,
            password=passsword).client

    def has_children(self, uri):
        """
        Checks whether an archival object has children using the tree/node endpoint.

        Checks the child_count attribute and if the value is greater than 0,
        return true, otherwise return False.
        """
        resp = self.client.get(uri)
        if resp.status_code == 404:
            raise MissingArchivalObjectError("{} cannot be found".format(uri))
        obj = resp.json()
        resource_uri = obj['resource']['ref']
        tree_node = self.client.get(f"{resource_uri}/tree/node?node_uri={uri}").json()
        return True if tree_node['child_count'] > 0 else False

    def tree_root(self, resource_uri):
        """Gets a resource tree starting at the root."""
        return self.client.get(f"{resource_uri}/tree/root").json()

    def tree_node(self, resource_uri, node_uri):
        """Gets a resource tree starting at a node."""
        return self.client.get(f"{resource_uri}/tree/node?node_uri={node_uri}").json()

    def objects_within(self, uri_list):
        """Gets the number of objects which have a URI in their ancestors array."""
        count = 0
        for chunk in list_chunks(uri_list, 100):
            ancestors_param = ' '.join([f'ancestors:"{c}"' for c in chunk])
            search_uri = f"search?q={ancestors_param}&filter_query[]=publish:true&page=1&fields[]=uri&type[]=archival_object&page_size=1"
            result = self.client.get(search_uri)
            try:
                data = result.json()
                count += data["total_hits"]
            except Exception as e:
                raise Exception(f"Error fetching child counts for URI {search_uri}: {e}")
        return count

    def objects_before(self, target_node, initial_node, resource_uri, parent_uri=None):
        """Gets a count of previous archival objects in a resource."""
        count = 0
        target_position = target_node["position"] if ("position" in target_node) else target_node["_resolved"]["position"]
        for offset in range(initial_node["waypoints"]):
            results_url = (f"{resource_uri}/tree/waypoint?offset={offset}&parent_node={parent_uri}" if parent_uri else
                           f"{resource_uri}/tree/waypoint?offset={offset}")
            results_page = self.client.get(results_url).json()
            if target_position < ((offset + 1) * initial_node["waypoint_size"]):
                previous_results = [r for r in results_page if r["position"] < target_position]
                count += sum([self.objects_within([p["uri"] for p in previous_results]), len(previous_results)])
                count += 1
                return count
            count += sum([self.objects_within([r["uri"] for r in results_page]), len(results_page)])
            count += 1
        return count

    def resource_data(self, uri):
        """Fetches a resource record with data necessary for merging an Arrangement Map."""
        return self.client.get(uri, params={"resolve": ["subjects", "linked_agents"]}).json()


class CartographerClient(object):

    def __init__(self, baseurl):
        self.client = ElectronBond(baseurl=baseurl)

    def handle_reference(self, reference):
        reference["ref"] = reference["archivesspace_uri"]
        reference["type"] = "collection"
        del reference["archivesspace_uri"]
        return reference

    def resolve_component(self, uri):
        resp = self.client.get("/api/find-by-uri/", params={"uri": uri})
        resp.raise_for_status()
        json_data = resp.json()
        if json_data["count"] > 0:
            return json_data["results"][0]
        return None

    def objects_before(self, uri):
        resp = self.client.get(f"{uri.rstrip('/')}/objects_before/")
        resp.raise_for_status()
        json_data = resp.json()
        return json_data.get("count", 0)
