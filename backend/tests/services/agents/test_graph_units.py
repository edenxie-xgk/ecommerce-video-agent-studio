from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_creative_graph


def test_compiled_graph_has_expected_automatic_business_nodes() -> None:
    graph = build_creative_graph(InMemorySaver())

    business_nodes = {
        node_name for node_name in graph.get_graph().nodes if not node_name.startswith("__")
    }

    assert business_nodes == {
        "product_understanding",
        "creative_script",
        "storyboard_prompt",
        "prompt_check",
        "review_cost_gate",
    }
