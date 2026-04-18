#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect
from graphify.export import to_html, to_json, to_obsidian
from graphify.extract import extract
from graphify.report import generate as generate_report
from graphify.wiki import to_wiki

DEFAULT_OBSIDIAN_DIR = Path.home() / "vault" / "graphify" / "xcg-bot"
EXCLUDED_TOP_LEVEL_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "graph-builder",
    "graphify-out",
    "venv",
}


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_dir = script_dir.parent

    parser = argparse.ArgumentParser(
        description="Build the xcg-bot code graph from the local repository source."
    )
    parser.add_argument("--repo-dir", type=Path, default=repo_dir)
    parser.add_argument("--source-root", type=Path, default=repo_dir)
    parser.add_argument("--output-dir", type=Path, default=repo_dir / "graphify-out")
    parser.add_argument("--obsidian-dir", type=Path, default=DEFAULT_OBSIDIAN_DIR)
    parser.add_argument("--skip-obsidian", action="store_true")
    parser.add_argument("--skip-html", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def cleanup_markdown_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file() and child.suffix.lower() == ".md":
            child.unlink()


def cleanup_obsidian_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file() and child.suffix.lower() == ".md":
            child.unlink()


def is_included_code_file(path: Path, source_root: Path) -> bool:
    rel_parts = path.resolve().relative_to(source_root).parts
    return not any(part in EXCLUDED_TOP_LEVEL_DIRS for part in rel_parts)


def collect_code_files(source_root: Path) -> tuple[list[Path], dict]:
    detected = detect(source_root)
    code_files = [
        Path(file_path).resolve()
        for file_path in detected.get("files", {}).get("code", [])
        if is_included_code_file(Path(file_path), source_root)
    ]
    filtered_detection = {
        "files": {
            "code": [str(path) for path in code_files],
            "document": [],
            "paper": [],
            "image": [],
        },
        "total_files": len(code_files),
        "total_words": detected.get("total_words", 0),
    }
    return sorted(code_files), filtered_detection


def build_community_labels(graph: nx.Graph, communities: dict[int, list[str]]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for community_id, node_ids in communities.items():
        if not node_ids:
            labels[community_id] = f"Community {community_id}"
            continue

        source_counts: dict[str, int] = {}
        for node_id in node_ids:
            source_file = graph.nodes[node_id].get("source_file")
            if source_file:
                source_counts[source_file] = source_counts.get(source_file, 0) + 1

        dominant_source = max(source_counts, key=source_counts.get, default="")
        dominant_name = Path(dominant_source).stem.replace("_", " ").replace("-", " ").title()

        anchor_nodes = sorted(
            node_ids,
            key=lambda node_id: (
                graph.degree(node_id),
                len(graph.nodes[node_id].get("label", "")),
            ),
            reverse=True,
        )
        anchor_label = graph.nodes[anchor_nodes[0]].get("label", anchor_nodes[0]) if anchor_nodes else ""

        if dominant_name and anchor_label and anchor_label.lower() not in dominant_name.lower():
            labels[community_id] = f"{dominant_name} - {anchor_label}"[:80]
        elif dominant_name:
            labels[community_id] = dominant_name[:80]
        elif anchor_label:
            labels[community_id] = anchor_label[:80]
        else:
            labels[community_id] = f"Community {community_id}"
    return labels


def write_report(
    graph: nx.Graph,
    communities: dict[int, list[str]],
    cohesion: dict[int, float],
    community_labels: dict[int, str],
    output_path: Path,
    detection_result: dict,
    root_name: str,
) -> None:
    report = generate_report(
        graph,
        communities,
        cohesion,
        community_labels,
        god_nodes(graph),
        surprising_connections(graph, communities),
        detection_result,
        {"input": 0, "output": 0},
        root_name,
        suggested_questions=suggest_questions(graph, communities, community_labels),
    )
    output_path.write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_dir = args.repo_dir.expanduser().resolve()
    source_root = args.source_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    obsidian_dir = args.obsidian_dir.expanduser()
    wiki_dir = output_dir / "wiki"

    if not source_root.exists():
        raise SystemExit(f"Source root does not exist: {source_root}")
    if not source_root.is_dir():
        raise SystemExit(f"Source root is not a directory: {source_root}")
    if repo_dir not in source_root.parents and source_root != repo_dir:
        raise SystemExit(f"Source root must live inside repo dir: {source_root}")

    code_files, detection_result = collect_code_files(source_root)
    if not code_files:
        raise SystemExit(f"No code files found under {source_root}")

    if args.validate_only:
        print(f"Code graph inputs are valid for {source_root}: {len(code_files)} code files.")
        return 0

    extraction = extract(code_files, cache_root=output_dir / "cache")
    graph = build_from_json(extraction)
    graph.graph["hyperedges"] = extraction.get("hyperedges", [])

    communities = cluster(graph)
    cohesion = score_all(graph, communities)
    community_labels = build_community_labels(graph, communities)

    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_markdown_dir(wiki_dir)
    to_json(graph, communities, str(output_dir / "graph.json"))

    if not args.skip_html:
        to_html(graph, communities, str(output_dir / "graph.html"), community_labels=community_labels)

    to_wiki(
        graph,
        communities,
        wiki_dir,
        community_labels=community_labels,
        cohesion=cohesion,
        god_nodes_data=god_nodes(graph),
    )

    if not args.skip_obsidian:
        cleanup_obsidian_dir(obsidian_dir)
        to_obsidian(
            graph,
            communities,
            str(obsidian_dir),
            community_labels=community_labels,
            cohesion=cohesion,
        )

    write_report(
        graph,
        communities,
        cohesion,
        community_labels,
        output_dir / "GRAPH_REPORT.md",
        detection_result,
        repo_dir.name,
    )

    print(
        f"Code graph build complete: {graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges, {len(communities)} communities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

