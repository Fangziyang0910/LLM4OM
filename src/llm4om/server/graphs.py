"""The platform graph of every method as a module variable, for the LangGraph server (`llm4om serve`, langgraph.json)."""

from llm4om.graph import platform_graph
from llm4om.methods import methods

globals().update({method.id: platform_graph(method) for method in methods().values()})
