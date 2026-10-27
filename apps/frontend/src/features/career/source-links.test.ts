import {expect,it} from 'vitest';
import {sourceCitations,sourceLink} from './source-links';
it('uses actual source domains, preserving URLs and rejecting unsafe links',()=>{
 expect(sourceLink('https://www.example.test/reports?q=1#interview')).toEqual({domain:'example.test',url:'https://www.example.test/reports?q=1#interview'});
 for(const value of ['javascript:alert(1)','//example.test','https://secret@example.test','not a URL'])expect(sourceLink(value)).toBeNull();
 const sources=[{source_id:'one',url:'https://www.example.test/a(b)'},{source_id:'two',url:'https://other.test/report'}];
 expect(sourceCitations(['one','one','missing'],sources)).toBe('[example.test](<https://www.example.test/a(b)>)');
 expect(sourceCitations([],sources)).toBe('');
});
