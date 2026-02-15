import re


def list_chunks(lst, n):
    """Yield successive n-sized chunks from list.
    Args:
        lst (list): list to chunkify
        n (integer): size of chunk to produce
    """
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def indicator_to_integer(indicator):
    """Converts an instance indicator to an integer.

    An indicator can be an integer (23) a combination of integers and letters (23b)
    or just letters (B, Be). In cases where indicator data only consists of letters,
    the function will return an integer based on the ordinal value of the lowercased
    first letter in the indicator.
    """
    try:
        integer = int(indicator)
    except ValueError:
        parsed = re.sub("[^0-9]", "", indicator)
        if len(parsed):
            return indicator_to_integer(parsed)
        integer = ord(indicator[0].lower()) - 97
    return integer


def get_ancestors(obj):
    """Returns the full resolved record for each ancestor."""
    for a in obj["ancestors"]:
        yield a["_resolved"]


def closest_parent_value(obj, key):
    """Iterates upwards through a hierarchy and returns the first match for a key.

    Iterates up through an archival object's ancestors and returns the first
    value which matches a given key."""
    for ancestor in get_ancestors(obj):
        if ancestor.get(key) not in ['', [], {}, None]:
            return ancestor[key]


def closest_creators(obj):
    """Iterates upwards through a hierarchy and returns the first creator.

    Iterates up through an archival object's ancestors looking for linked agents,
    then iterates over the linked agents to see if it contains an agent with
    the role of creator. Returns the first creator it finds."""
    closest = []
    for ancestor in get_ancestors(obj):
        closest = [c for c in ancestor.get("linked_agents") if c.get("role") == "creator"]
    return closest


def get_date_string(dates):
    date_strings = []
    for date in dates:
        if date.get("expression"):
            date_strings.append(date["expression"])
        elif all([date.get("begin"), date.get("end")]):
            date_strings.append("{}-{}".format(date["begin"], date["end"]))
        else:
            date_strings.append(date["begin"])
    return ", ".join(date_strings)
