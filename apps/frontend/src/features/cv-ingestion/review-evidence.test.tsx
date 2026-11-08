import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {ReviewEvidence} from './review-evidence';
import type {ReviewFact} from './types';

describe('multiple facts in one review category',()=>{
 it('renders both contributions and updates one without losing the other',()=>{
  const error=vi.spyOn(console,'error');
  const facts:ReviewFact[]=[
   {field:'personal_contribution',skill_name:null,attribution:'personal',status:'supported',value:'Designed the editor.',evidence:[{source_id:'b1',quote:'I designed the editor.'}]},
   {field:'personal_contribution',skill_name:null,attribution:'shared',status:'supported',value:'Co-developed the pipeline.',evidence:[{source_id:'b1',quote:'We co-developed the pipeline.'}]},
  ];
  try{
   const view=render(<ReviewEvidence facts={facts}/>);
   expect(screen.getByText('Designed the editor.')).toBeInTheDocument();
   expect(screen.getByText('Co-developed the pipeline.')).toBeInTheDocument();
   expect(screen.getByText('Personal contribution')).toBeInTheDocument();
   expect(screen.getByText('Shared contribution')).toBeInTheDocument();
   view.rerender(<ReviewEvidence facts={[{...facts[0],value:'Designed and tested the editor.'},facts[1]]}/>);
   expect(screen.getByText('Designed and tested the editor.')).toBeInTheDocument();
   expect(screen.getByText('Co-developed the pipeline.')).toBeInTheDocument();
   expect(error.mock.calls.flat().join(' ')).not.toMatch(/same key|unique.*key/i);
  }finally{error.mockRestore();}
 });
});
