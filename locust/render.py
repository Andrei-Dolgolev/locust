"""
Rendering utilities for locust parse results.
"""
import copy
from dataclasses import asdict, dataclass
import json
import os
import textwrap
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import lxml
from lxml.html import builder as E
import yaml

from . import parse

IndexKey = Tuple[str, Optional[str], str, int]


@dataclass
class NestedChange:
    key: IndexKey
    change: parse.LocustChange
    children: Any


def get_key(change: parse.LocustChange) -> IndexKey:
    return (change.filepath, change.revision, change.name, change.line)


def parent_key(change: parse.LocustChange) -> Optional[IndexKey]:
    if change.parent is None:
        return None
    return (
        change.filepath,
        change.revision,
        change.parent[0],
        change.parent[1],
    )


def nest_results(
    changes: List[parse.LocustChange],
) -> Dict[str, List[NestedChange]]:
    results: Dict[str, List[NestedChange]] = {}
    index: Dict[IndexKey, parse.LocustChange] = {
        get_key(change): change for change in changes
    }

    children: Dict[IndexKey, List[IndexKey]] = {key: [] for key in index}

    for change in changes:
        change_parent = parent_key(change)
        if change_parent:
            children[change_parent].append(get_key(change))

    nested_results: Dict[str, List[NestedChange]] = {}
    keys_to_process = sorted(
        [k for k in index], key=lambda k: len(children[k]), reverse=True
    )
    visited_keys: Set[IndexKey] = set()

    def process_change(change_key: IndexKey, visited: Set[IndexKey]) -> NestedChange:
        visited.add(change_key)
        if not children[change_key]:
            return NestedChange(key=change_key, change=index[change_key], children=[])

        change_children = [
            process_change(child_key, visited) for child_key in children[change_key]
        ]
        return NestedChange(
            key=change_key,
            change=index[change_key],
            children=change_children,
        )

    for key in keys_to_process:
        if key in visited_keys:
            continue
        change = index[key]
        if change.filepath not in results:
            results[change.filepath] = []

        nested_change = process_change(key, visited_keys)

        results[change.filepath].append(nested_change)

    return results


def repo_relative_filepath(
    repo_dir: str, change: parse.LocustChange
) -> parse.LocustChange:
    """
    Changes the filepath on a LocustChange so that it is relative to the repo directory.
    """
    updated_change = copy.copy(change)
    updated_change.filepath = os.path.relpath(change.filepath, start=repo_dir)
    return updated_change


def nested_change_to_dict(nested_change: NestedChange) -> Dict[str, Any]:
    result = {
        "name": nested_change.change.name,
        "type": nested_change.change.change_type,
        "line": nested_change.change.line,
        "changed_lines": nested_change.change.changed_lines,
        "total_lines": nested_change.change.total_lines,
    }

    children_list: List[Dict[str, Any]] = []
    if nested_change.children:
        children_list = [
            nested_change_to_dict(child) for child in nested_change.children
        ]

    result["children"] = children_list

    return result


def results_dict(raw_results: Dict[str, List[NestedChange]]) -> Dict[str, Any]:
    results = {
        "locust": [
            {
                "file": filepath,
                "changes": [
                    nested_change_to_dict(nested_change)
                    for nested_change in nested_changes
                ],
            }
            for filepath, nested_changes in raw_results.items()
        ]
    }

    return results


def render_json(results: Dict[str, Any]) -> str:
    return json.dumps(results)


def render_yaml(results: Dict[str, Any]) -> str:
    return yaml.dump(results, sort_keys=False)


def render_change_as_html(
    change: Dict[str, Any], filepath: str, current_depth: int, max_depth: int
) -> Optional[Any]:
    if current_depth >= max_depth:
        return None

    link = change.get("link")
    if link is None:
        link = filepath

    change_elements: List[Any] = [
        E.B("Name: "),
        E.A(change["name"], href=link),
        E.BR(),
        E.B("Type: "),
        E.SPAN(change["type"]),
        E.BR(),
        E.B("Changed lines: "),
        E.SPAN(str(change["changed_lines"])),
    ]

    if change["total_lines"]:
        change_elements.extend(
            [E.BR(), E.B("Total lines: "), E.SPAN(str(change["total_lines"]))]
        )

    if change["children"]:
        change_elements.extend([E.BR(), E.B("Changes:")])
    child_elements = []
    for child in change["children"]:
        child_elements.append(
            render_change_as_html(child, filepath, current_depth + 1, max_depth)
        )
    change_elements.append(E.UL(*child_elements))

    return E.LI(*change_elements)


def html_file_section_handler_vanilla(item: Dict[str, Any]) -> Any:
    filepath = item["file"]
    change_elements = [
        render_change_as_html(change, filepath, 0, 2) for change in item["changes"]
    ]
    file_elements = [
        E.H4(E.A(filepath, href=filepath)),
        E.B("Changes:"),
        E.UL(*change_elements),
    ]
    return E.DIV(*file_elements)


def html_file_section_handler_github(item: Dict[str, Any]) -> Any:
    filepath = item["file"]
    change_elements = [
        render_change_as_html(change, filepath, 0, 2) for change in item["changes"]
    ]
    file_summary_element = E.H4(E.A(filepath, href=filepath))
    file_elements = [
        E.B("Changes:"),
        E.UL(*change_elements),
    ]
    file_elements_div = E.DIV(*file_elements)
    file_details_element = E.DIV(
        lxml.html.fromstring(
            f"<details><summary>{lxml.html.tostring(file_summary_element).decode()}</summary>"
            f"{lxml.html.tostring(file_elements_div).decode()}</details>"
        )
    )
    return file_details_element


def generate_render_html(
    file_section_handler: Callable[[Dict[str, Any]], Any]
) -> Callable[[Dict[str, Any]], str]:
    def render_html(results: Dict[str, Any]) -> str:
        heading = E.H2("Locust summary")
        body_elements = [heading]

        refs = results.get("refs")
        if refs is not None:
            body_elements.extend([E.H3("Git references")])
            body_elements.extend([E.B("Initial: "), E.SPAN(refs["initial"]), E.BR()])
            if refs["terminal"] is not None:
                body_elements.extend(
                    [E.B("Terminal: "), E.SPAN(refs["terminal"]), E.BR()]
                )

        body_elements.append(E.HR())

        changes_by_file = results["locust"]
        for item in changes_by_file:
            item_element = file_section_handler(item)
            body_elements.append(item_element)

        html = E.HTML(E.BODY(*body_elements))
        results_string = lxml.html.tostring(html).decode()
        return results_string

    return render_html


def enrich_with_refs(
    results: Dict[str, Any], initial_ref: str, terminal_ref: Optional[str]
) -> Dict[str, Any]:
    enriched_results = copy.deepcopy(results)
    enriched_results["refs"] = {
        "initial": initial_ref,
        "terminal": terminal_ref,
    }
    return enriched_results


# TODO(neeraj): Recursively enrich change children with GitHub links
def enrich_with_github_links(
    results: Dict[str, Any], github_repo_url: str, terminal_ref: Optional[str]
) -> Dict[str, Any]:
    if terminal_ref is None:
        raise ValueError("Cannot create GitHub links without a reference to link to")

    if github_repo_url[-1] == "/":
        github_repo_url = github_repo_url[:-1]

    enriched_results = copy.deepcopy(results)

    for item in enriched_results["locust"]:
        relative_filepath = "/".join(item["file"].split(os.sep))
        if relative_filepath[0] == "/":
            relative_filepath = relative_filepath[1:]
        filepath = f"{github_repo_url}/blob/{terminal_ref}/{relative_filepath}"
        item["file"] = filepath
        for change in item["changes"]:
            change["link"] = f"{filepath}#L{change['line']}"

    return enriched_results


renderers: Dict[str, Callable[[Dict[str, List[NestedChange]]], str]] = {
    "json": render_json,
    "yaml": render_yaml,
    "html": generate_render_html(html_file_section_handler_vanilla),
    "html-github": generate_render_html(html_file_section_handler_github),
}
