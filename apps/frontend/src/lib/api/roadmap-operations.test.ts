import { afterEach, expect, it, vi } from 'vitest';
import { roadmapApi } from './roadmap';
afterEach(() => vi.unstubAllGlobals());
it.each(['/planner/outlines/generate', '/planner/weeks/generate'])('accepts the operation response from %s', async path => {
 const operation = {version: 7, operation: {id: 'synthetic-operation', status: 'pending', stage: 'writing'}};
 vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(operation), {status: 202})));
 await expect(roadmapApi(path, 'synthetic', {mutation_id: 'synthetic-mutation'})).resolves.toEqual(operation);
});
it('still rejects an operation response without a valid version', async () => {
 vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({operation: null}), {status: 202})));
 await expect(roadmapApi('/planner/weeks/generate', 'synthetic', {})).rejects.toMatchObject({code: 'invalid_response'});
});
