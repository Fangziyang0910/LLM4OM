"""The platform graph of every method as a module variable, for the LangGraph server (`llm4om serve`, langgraph.json)."""

from llm4om.agent import optimization_graph, solution_graph
from llm4om.graph import platform_graph
from llm4om.methods import methods
from llm4om.requirements import requirements_graph

globals().update({method.id: platform_graph(method) for method in methods().values()})
requirements = requirements_graph()
solution_chat = solution_graph()
optimization = optimization_graph()
