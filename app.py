"""Streamlit UI for OptiStock AI

Entry point for the interactive demo. Initializes the graph and
delegates to the ui package for layout and rendering.
"""

import sys
from pathlib import Path

# Add project root to path so we can import from tools/domain
_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

import streamlit as st
from langgraph.checkpoint.memory import MemorySaver

from graph import build_graph
from ui.layout import render_app


st.set_page_config(page_title="OptiStock AI Stockout Resolution", page_icon="📦", layout="wide")


@st.cache_resource
def get_graph():
    """Cache the graph instance (and its in-memory checkpointer) across runs."""
    return build_graph(checkpointer=MemorySaver())


def main():
    graph = get_graph()
    render_app(graph)


if __name__ == "__main__":
    main()
