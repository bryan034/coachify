"""Stage router; production uses one Gemini 3.5 Flash Lite adapter for both roles."""



class ModelRouter:
    def __init__(self,primary,context):
        self.primary,self.context=primary,context
        self.settings=primary.settings
        self.context_enabled=context is not None and getattr(getattr(context,'settings',None),'enabled',True)

    async def generate(self,request,operation,**kwargs):
        adapter=self.context if request.stage in ('context_route','context_answer','research_plan','research_assess','opportunity_plan','discovery_turn','discovery_plan','discovery_summary') else self.primary
        if adapter is None:
            from app.ai.adapter import AIError
            raise AIError('not_configured')
        return await adapter.generate(request,operation,**kwargs)


def opportunity_models(primary,context,gemini,settings,client):
    """Use the same Gemini model for planning, evaluation and summaries.

    Injected test/custom adapters retain the existing router interface. Production
    supplies Gemini settings and never falls back to a legacy provider or key.
    """
    if gemini is not None:
        return ModelRouter(primary,primary)
    return ModelRouter(primary,context) if context is not None else primary


def chat_models(state):
    """Prefer explicit chat configuration; use research Gemini when chat is disabled."""
    if getattr(state.ai,'context_enabled',False):return state.ai
    return getattr(state,'chat_ai',state.ai)
