import {act, renderHook, waitFor} from '@testing-library/react';
import {expect, it} from 'vitest';
import {useSection} from './workspace-summary';

function deferred<T>() {
 let resolve!: (value: T) => void, reject!: (cause: unknown) => void;
 const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
 return {promise, resolve, reject};
}

it('keeps showing the loaded data while the same account reloads it',async()=>{
 const first=deferred<string>(),second=deferred<string>();
 const {result,rerender}=renderHook(({load,token})=>useSection(load,token),{initialProps:{load:()=>first.promise,token:'one'}});
 expect(result.current.state).toEqual({status:'loading'});
 await act(async()=>first.resolve('first'));
 expect(result.current.state).toEqual({status:'ready',data:'first'});
 rerender({load:()=>second.promise,token:'one'});
 expect(result.current.state).toEqual({status:'ready',data:'first'});
 await act(async()=>second.resolve('second'));
 expect(result.current.state).toEqual({status:'ready',data:'second'});
});

it('starts again for another account and reports a failed reload',async()=>{
 const first=deferred<string>(),other=deferred<string>(),failing=deferred<string>();
 const {result,rerender}=renderHook(({load,token})=>useSection(load,token),{initialProps:{load:()=>first.promise,token:'one'}});
 await act(async()=>first.resolve('mine'));
 rerender({load:()=>other.promise,token:'two'});
 expect(result.current.state).toEqual({status:'loading'});
 await act(async()=>other.resolve('theirs'));
 rerender({load:()=>failing.promise,token:'two'});
 await act(async()=>failing.reject(new Error('Unavailable right now.')));
 await waitFor(()=>expect(result.current.state).toEqual({status:'error',message:'Unavailable right now.'}));
});
