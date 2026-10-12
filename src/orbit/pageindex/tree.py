"""Markdown to section tree, using PageIndex's own Markdown parser."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PageIndexError

TREE_SCHEMA = "pageindex-md-v1"


@dataclass(frozen=True, slots=True)
class Section:
    node_id: str
    parent_id: str | None
    title: str
    path: tuple[str, ...]
    level: int
    line_num: int
    text: str


def build_sections(markdown: str, title: str) -> list[Section]:
    """Return sections in document order.

    The parser is ``pageindex.page_index_md`` (heading levels 1-6, bold-only
    headings, code fences ignored). Celestin adds two things it lacks so no
    source text is lost: text before the first heading becomes a ``(preamble)``
    section, and a document without headings becomes one section titled ``title``.
    """
    try:
        from pageindex.page_index_md import (
            build_tree_from_nodes,
            extract_node_text_content,
            extract_nodes_from_markdown,
        )
    except ImportError as exc:
        raise PageIndexError(
            "pageindex is not installed; run: pip install 'celestin-memory[pageindex]'"
        ) from exc

    nodes, lines = extract_nodes_from_markdown(markdown)
    if not nodes:
        return [Section("0001", None, title, (title,), 1, 1, markdown.strip())] if markdown.strip() else []
    flat = extract_node_text_content(nodes, lines)
    preamble = "\n".join(lines[: flat[0]["line_num"] - 1]).strip()
    if preamble:
        flat.insert(0, {"title": "(preamble)", "line_num": 1, "level": 1, "text": preamble})
    sections: list[Section] = []

    def walk(tree_nodes, parent: Section | None) -> None:
        for node in tree_nodes:
            path = (*(parent.path if parent else ()), node["title"])
            section = Section(
                node_id=node["node_id"],
                parent_id=parent.node_id if parent else None,
                title=node["title"],
                path=path,
                level=len(path),
                line_num=node["line_num"],
                text=node["text"],
            )
            sections.append(section)
            walk(node["nodes"], section)

    walk(build_tree_from_nodes(flat), None)
    return sections
