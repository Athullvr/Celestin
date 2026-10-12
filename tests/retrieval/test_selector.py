import pytest

from orbit.retrieval.selector import Plan, SelectorContext, classify, plan_query, validate_plan

ALL = frozenset({"fts", "semantic", "sections", "pageindex"})


def ctx(available=ALL, docs=True, budget=4000, nav=3000):
    return SelectorContext(frozenset(available), docs, budget, nav)


@pytest.mark.parametrize("query, feature", [
    ("ERR_PAYMENT_4471", "identifier"), ("open src/app/main.py", "identifier"), ('"exact phrase" here', "identifier"),
    ("traceback in the worker", "identifier"), ("login bug", "short"),
    ("what does the architecture doc say", "doc_intent"), ("compare the two designs across sections", "multi_section"),
    ("why did we decide on sqlite earlier", "discussion"), ("why is startup slow", "question"),
])
def test_feature_classification(query, feature):
    assert feature in classify(query)


@pytest.mark.parametrize("query, primary", [
    ("ERR_PAYMENT_4471", "fts"),
    ("where is retrieve_context defined", "fts"),
    ("what does the documentation say about installation", "sections"),
    ("compare all the retrieval designs in the documentation across sections", "pageindex"),
    ("why did we decide to avoid a hosted database", "semantic"),
    ("how big is the default embedding model download", "sections"),
])
def test_primary_strategy_rules(query, primary):
    plan = plan_query(query, ctx())
    assert plan.primary == primary and plan.fallback != plan.primary and len(plan.strategies) <= 2


def test_unavailable_strategies_are_never_selected():
    assert plan_query("what does the documentation say about installation", ctx({"fts"}, docs=False)).strategies == ("fts",)
    plan = plan_query("why did we decide to avoid a hosted database", ctx({"fts", "sections"}))
    assert plan.primary == "fts"
    no_docs = plan_query("what does the documentation say about installation", ctx(docs=False))
    assert "sections" not in no_docs.strategies and "pageindex" not in no_docs.strategies


def test_pageindex_needs_docs_budget_and_reasonable_cost():
    q = "compare all the retrieval designs in the documentation across sections"
    assert plan_query(q, ctx(budget=200)).primary != "pageindex"
    assert plan_query(q, ctx(nav=90_000)).primary != "pageindex"
    assert plan_query(q, ctx(available=ALL - {"pageindex"})).primary == "sections"
    assert plan_query(q, ctx(docs=False)).primary != "pageindex"


def test_pageindex_is_an_escalation_after_sections_when_justified():
    plan = plan_query("what does the documentation say about installation", ctx())
    assert (plan.primary, plan.fallback) == ("sections", "pageindex")
    assert plan_query("what does the documentation say about installation", ctx(budget=100)).fallback != "pageindex"


def test_validate_plan_repairs_invalid_plans():
    fixed = validate_plan(Plan("pageindex", "pageindex", "x"), ctx(docs=False))
    assert fixed.primary == "fts" and fixed.fallback is None and "adjusted" in fixed.reason
    assert validate_plan(Plan("bogus", "fts", "x"), ctx()).primary == "fts"
    assert validate_plan(Plan("fts", "fts", "x"), ctx()).fallback is None


def test_selection_is_deterministic():
    q = "how do we configure the server according to the docs"
    assert plan_query(q, ctx()) == plan_query(q, ctx())
