"""Route context work to Gemini, reasoning/extraction/edits to the primary provider."""


class ModelRouter:
    def __init__(self,primary,context):
        self.primary,self.context=primary,context
        self.settings=primary.settings
        self.context_enabled=context is not None and getattr(getattr(context,'settings',None),'enabled',True)

    async def generate(self,request,operation,**kwargs):
        adapter=self.context if request.stage in ('context_route','context_answer','research_plan','research_assess','opportunity_plan','opportunity_summary') else self.primary
        if adapter is None:
            from app.ai.adapter import AIError
            raise AIError('not_configured')
        return await adapter.generate(request,operation,**kwargs)


def opportunity_models(primary,context,gemini,settings,client):
    """Public research has its own opt-in; Gemini chat may remain disabled."""
    from app.ai.adapter import AIAdapter
    if gemini is not None and settings.enabled and gemini.api_key.get_secret_value().strip():
        context=AIAdapter(gemini.model_copy(update={'enabled':True,'model':settings.gemini_model,'max_output_tokens':2048}),client)
    elif isinstance(context,AIAdapter):
        context=AIAdapter(context.settings.model_copy(update={'model':settings.gemini_model,'max_output_tokens':2048}),client)
    return ModelRouter(primary,context) if context is not None else primary
