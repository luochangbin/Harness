import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForEvent } from '../dist/event-stream.js';

test('SSE parser waits for a complete frame and decodes JSON data', async () => {
  const response = new Response('event: progress\ndata: {"sessionID":"s1","status":"running"}\n\n');
  const event = await waitForEvent(response, 1000);
  assert.deepEqual(event, {
    event: 'progress',
    data: { sessionID: 's1', status: 'running' }
  });
});

test('SSE timeout returns no event instead of inventing completion', async () => {
  const response = new Response(new ReadableStream({
    start() {}
  }));
  assert.equal(await waitForEvent(response, 1000), null);
});
