import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { chatEnterKey } from './chat-keyboard';

function Composer({ send, initial, maxLength }: { send: () => void; initial: string; maxLength?: number }) {
 const [value, setValue] = useState(initial);
 return <textarea aria-label="Message" value={value} maxLength={maxLength} onChange={event => setValue(event.target.value)} onKeyDown={event => chatEnterKey(event, send, setValue)} />;
}
const setup = (initial = 'hello', maxLength?: number) => {
 const send = vi.fn();
 render(<Composer send={send} initial={initial} maxLength={maxLength} />);
 return { send, box: screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement };
};

test('Enter sends without adding a line', () => {
 const { send, box } = setup();
 expect(fireEvent.keyDown(box, { key: 'Enter' })).toBe(false);
 expect(send).toHaveBeenCalledTimes(1);
 expect(box).toHaveValue('hello');
});

test.each([['Cmd', { metaKey: true }], ['Ctrl', { ctrlKey: true }]])('%s+Enter adds a line at the caret, replaces any selection and does not send', (_name, modifier) => {
 const { send, box } = setup();
 box.setSelectionRange(2, 2);
 fireEvent.keyDown(box, { key: 'Enter', ...modifier });
 expect(box).toHaveValue('he\nllo');
 expect([box.selectionStart, box.selectionEnd]).toEqual([3, 3]);
 box.setSelectionRange(3, 6);
 fireEvent.keyDown(box, { key: 'Enter', ...modifier });
 expect(box).toHaveValue('he\n\n');
 expect(send).not.toHaveBeenCalled();
});

test('a new line respects the message limit', () => {
 const { send, box } = setup('12345', 5);
 box.setSelectionRange(5, 5);
 fireEvent.keyDown(box, { key: 'Enter', metaKey: true });
 expect(box).toHaveValue('12345');
 expect(send).not.toHaveBeenCalled();
});

test('Shift+Enter keeps the browser new line, and IME confirmation and other keys do not send', () => {
 const { send, box } = setup();
 expect(fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })).toBe(true);
 expect(fireEvent.keyDown(box, { key: 'Enter', isComposing: true })).toBe(true);
 expect(fireEvent.keyDown(box, { key: 'a' })).toBe(true);
 expect(send).not.toHaveBeenCalled();
});
