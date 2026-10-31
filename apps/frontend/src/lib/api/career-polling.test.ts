import {afterEach,expect,it,vi} from 'vitest';
import {ApiError} from './profile';
import {CareerApiError} from './career';
import {retryCareerRead} from './career-polling';

afterEach(()=>vi.useRealTimers());

it('retries interrupted reads with bounded backoff and returns the saved result',async()=>{
 vi.useFakeTimers();const notify=vi.fn();
 const read=vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockRejectedValueOnce(new ApiError('Gateway unavailable',502)).mockResolvedValue({phase:'ready'});
 const result=retryCareerRead(read,undefined,notify);
 await vi.advanceTimersByTimeAsync(1999);expect(read).toHaveBeenCalledTimes(1);
 await vi.advanceTimersByTimeAsync(1);expect(read).toHaveBeenCalledTimes(2);
 await vi.advanceTimersByTimeAsync(4000);
 await expect(result).resolves.toEqual({phase:'ready'});expect(notify).toHaveBeenCalledTimes(2);
});

it.each([new ApiError('Sign in again',401),new ApiError('Not found',404),new CareerApiError('Invalid model answer',503,'invalid_output'),new CareerApiError('Model unavailable',503,'unavailable')])('does not retry terminal failures: %s',async(error)=>{
 const read=vi.fn().mockRejectedValue(error);
 await expect(retryCareerRead(read)).rejects.toBe(error);expect(read).toHaveBeenCalledTimes(1);
});

it('stops after five failed reads and leaves recovery to the existing retry control',async()=>{
 vi.useFakeTimers();const error=new ApiError('Unavailable',503),read=vi.fn().mockRejectedValue(error);
 const failure=expect(retryCareerRead(read)).rejects.toBe(error);
 await vi.runAllTimersAsync();await failure;expect(read).toHaveBeenCalledTimes(5);
});

it('cancels pending read retries when leaving the chat',async()=>{
 vi.useFakeTimers();const controller=new AbortController(),read=vi.fn().mockRejectedValue(new TypeError('Offline'));
 const failure=expect(retryCareerRead(read,controller.signal)).rejects.toMatchObject({name:'AbortError'});
 await vi.advanceTimersByTimeAsync(1);controller.abort();await failure;
 await vi.runAllTimersAsync();expect(read).toHaveBeenCalledTimes(1);
});
