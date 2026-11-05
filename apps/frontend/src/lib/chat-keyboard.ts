import type { KeyboardEvent } from 'react';
import { flushSync } from 'react-dom';

export const chatKeyHint = 'Enter to send · Cmd+Enter for a new line';

/** Shared chat composer keys: Enter sends; Cmd+Enter (Ctrl+Enter off Mac) adds a line, which browsers do not do themselves. */
export function chatEnterKey(event: KeyboardEvent<HTMLTextAreaElement>, send: () => void, setValue: (value: string) => void) {
 if (event.key !== 'Enter' || event.nativeEvent.isComposing) return;
 if (event.metaKey || event.ctrlKey) {
  event.preventDefault();
  const box = event.currentTarget;
  const { selectionStart: start, selectionEnd: end, value, maxLength } = box;
  const next = `${value.slice(0, start)}\n${value.slice(end)}`;
  if (maxLength >= 0 && next.length > maxLength) return;
  const atEnd = end === value.length;
  flushSync(() => setValue(next));
  box.setSelectionRange(start + 1, start + 1);
  if (atEnd) box.scrollTop = box.scrollHeight;
  return;
 }
 if (event.shiftKey || event.altKey) return;
 event.preventDefault();
 send();
}
