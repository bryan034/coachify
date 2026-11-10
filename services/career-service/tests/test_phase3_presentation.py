import asyncio
from app.workflows.goal_summary import summarize
from tests.test_goal_chat_presentation import environment

def test_summary_is_reused_only_for_the_same_owner_goal_and_research_revision():
    async def run():
        request,body,checks,calls,record=environment()
        class Rows:
            row=None
            def find_one(self,query,projection):
                return self.row if self.row and self.row['goal_summary']['key']==query['goal_summary.key'] else None
            def update_one(self,query,update):self.row=update['$set']
        rows=Rows();request.app.state.workspace_store.rows=rows
        first=await summarize(request,'owner',body)
        second=await summarize(request,'owner',body)
        assert first==second and len(calls)==1
        record.version=2
        await summarize(request,'owner',body)
        assert len(calls)==2
    asyncio.run(run())
