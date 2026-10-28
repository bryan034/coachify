"""Separate transient exploration-turn graph; no raw CV/checkpoint persistence."""
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context

async def exploration_turn(generate):
    async def coach(state):return {'result':await generate()}
    graph=StateGraph(dict);graph.add_node('understand_interests',coach)
    graph.add_edge(START,'understand_interests');graph.add_edge('understand_interests',END)
    with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
    return result['result']
