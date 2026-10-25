import {fireEvent,render,screen,within} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import {RequirementEditor} from './requirement-editor';
import type {JDExtraction,SavedReview} from '@/lib/api/career';
const content:JDExtraction={role:'Analyst',field:'Data',company:null,location:null,seniority_level:null,job_url:null,summary:null,responsibilities:[],
 skills:[{item_id:'stable-sql-item',skill_id:'language.sql',name:'SQL',category:'Technical',priority:'required',origin:'employer',evidence:'SQL for analysis.',group_id:'entry',group_operator:'any'}],
 non_skill_requirements:[{requirement_id:'degree-item',description:'Degree or equivalent experience.',category:'qualification',priority:'preferred',evidence:'Degree or experience.',group_id:'entry',group_operator:'any'}]};
const review:SavedReview={review_id:'000000000000000000000081',version:2,target_type:'specific_job',extraction:content,baseline:content,metadata_origins:{},requirements_need_review:false,is_confirmed:false,generation:{}};
test('metadata edits stay local until Save, and reset/cancel retain the saved baseline',()=>{
 const onSave=vi.fn(),onCancel=vi.fn();render(<RequirementEditor review={review} busy={false} onSave={onSave} onCancel={onCancel}/>);
 fireEvent.change(screen.getByRole('textbox',{name:'Role'}),{target:{value:'Engineer'}});
 expect(onSave).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Reset role details'}));
 expect(screen.getByRole('textbox',{name:'Role'})).toHaveValue('Analyst');
 fireEvent.click(screen.getByRole('button',{name:'Cancel edits'}));expect(onCancel).toHaveBeenCalledOnce();expect(onSave).not.toHaveBeenCalled();
});
test('moving a skill to conditions saves its identity and OR relationship in one update',()=>{
 const onSave=vi.fn();render(<RequirementEditor review={review} busy={false} onSave={onSave} onCancel={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Move SQL to conditions'}));
 fireEvent.click(screen.getByRole('button',{name:'Save review'}));
 expect(onSave).toHaveBeenCalledOnce();const [saved]=onSave.mock.calls[0];
 expect(saved.skills).toEqual([]);expect(saved.non_skill_requirements[1]).toMatchObject({requirement_id:'stable-sql-item',group_id:'entry',group_operator:'any'});
 expect(saved.non_skill_requirements[0].requirement_id).toBe('degree-item');
});
test('adding and editing conditions retains durations and explicit context acknowledgement',()=>{
 const onSave=vi.fn();render(<RequirementEditor review={review} busy={false} onSave={onSave} onCancel={vi.fn()}/>);
 fireEvent.change(screen.getByRole('textbox',{name:'Company'}),{target:{value:'Example'}});
 fireEvent.click(screen.getByRole('checkbox',{name:/I have reviewed the requirements/}));
 fireEvent.change(screen.getByRole('spinbutton',{name:'Minimum experience (months)'}),{target:{value:'12'}});
 fireEvent.change(screen.getByRole('spinbutton',{name:'Maximum experience (months)'}),{target:{value:'36'}});
 fireEvent.click(screen.getByRole('button',{name:'Save review'}));
 expect(onSave.mock.calls[0][0].non_skill_requirements[0]).toMatchObject({minimum_months:12,maximum_months:36});
 expect(onSave.mock.calls[0][1]).toBe(true);
});
