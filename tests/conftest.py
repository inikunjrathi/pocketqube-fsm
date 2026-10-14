from __future__ import annotations

def pytest_collection_modifyitems(items):
    for item in items:
        marker = item.get_closest_marker("requirement")
        if marker is None:
            continue
        for req_id in marker.args:
            item.user_properties.append(("requirement", req_id))
