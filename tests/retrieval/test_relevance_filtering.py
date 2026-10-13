"""Section relevance filtering: margin semantics, top-K cap with exemptions, excerpts, and safety."""

import math

import pytest

from orbit.retrieval.relevance import excerpt_section, margin_keep, top_k_with_exemptions

# ---- margin semantics -----------------------------------------------------

def test_margin_keeps_hits_within_the_margin_of_the_best():
    assert margin_keep([0.80, 0.78, 0.70, 0.60], 0.08) == [True, True, False, False]
    assert margin_keep([0.80, 0.73], 0.08) == [True, True]  # within the margin (an exact boundary is float-sensitive)


def test_margin_edge_cases():
    assert margin_keep([], 0.1) == []
    assert margin_keep([0.7], 0.0) == [True]  # single hit always kept
    assert margin_keep([0.5, 0.5, 0.5], 0.0) == [True, True, True]  # ties with the best are all kept
    assert margin_keep([0.9, 0.1], None) == [True, True]  # disabled
    assert margin_keep([0.0, 0.0], 0.04) == [True, True]  # zeros
    assert margin_keep([-0.2, -0.3, -0.9], 0.15) == [True, True, False]  # negative scores: only differences matter
    assert margin_keep([None, 0.9, 0.5], 0.1) == [True, True, False]  # missing scores are never silently dropped
    assert margin_keep([None, None], 0.1) == [True, True]
    assert margin_keep([math.nan, 0.9, 0.2], 0.1) == [True, True, False]


# ---- top-K cap -------------------------------------------------------------

def test_top_k_keeps_first_k_plus_exempt():
    ids = ["a", "b", "c", "d", "e"]
    assert top_k_with_exemptions(ids, 2, set()) == {"a", "b"}
    assert top_k_with_exemptions(ids, 2, {"e", "zzz"}) == {"a", "b", "e"}  # exempt only if present
    assert top_k_with_exemptions(ids, None, set()) == set(ids)
    assert top_k_with_exemptions([], 3, {"x"}) == set()


# ---- excerpts --------------------------------------------------------------

LONG = ("## Storage\n\nIntro paragraph about nothing in particular " + "x" * 300 + "\n\n"
        "The vector store is sqlite-vec and the model download is 130 MB.\n\n"
        "```\ncode line one\n\ncode line after blank\n```\n\n"
        "Closing paragraph about unrelated topics " + "y" * 300 + "\n")


def test_short_sections_are_returned_whole():
    assert excerpt_section("## A\n\nshort", 10, "anything", 1200) == ("## A\n\nshort", None)
    assert excerpt_section(LONG, 10, "model download", None) == (LONG, None)


def test_excerpt_keeps_heading_and_best_matching_paragraph_with_original_line_ranges():
    text, ranges = excerpt_section(LONG, 100, "how big is the model download", 400)
    assert text.startswith("## Storage") and "130 MB" in text and "Intro paragraph" not in text
    assert "[...]" in text and len(text.encode()) <= 400 + 200
    lines = LONG.split("\n")
    for start, end in ranges:
        assert "\n".join(lines[start - 100: end - 100 + 1]) in text  # ranges point at the original lines
    assert ranges[0] == (100, 100)  # the heading line itself


def test_excerpt_never_splits_code_blocks_and_falls_back_without_overlap():
    text, ranges = excerpt_section(LONG, 1, "code line after blank", 300)
    assert "code line one\n\ncode line after blank" in text  # blank line inside the fence did not split it
    fallback, _ = excerpt_section(LONG, 1, "zzzz qqqq", 300)
    assert "Intro paragraph" in fallback  # no overlap: first paragraph instead of nothing


def test_excerpt_is_deterministic():
    assert excerpt_section(LONG, 5, "model download", 400) == excerpt_section(LONG, 5, "model download", 400)
