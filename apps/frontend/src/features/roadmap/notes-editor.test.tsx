import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NotesEditor, fromElement, toHtml } from './notes-editor';
import type { NotesDocument } from './types';

const doc: NotesDocument = { blocks: [
 { type: 'heading', runs: [{ text: 'What I did' }] },
 { type: 'paragraph', runs: [{ text: 'Set up ' }, { text: 'pytest', bold: true }, { text: ' today.' }] },
 { type: 'bullet', runs: [{ text: 'Read the docs' }] },
 { type: 'bullet', runs: [{ text: 'Write a test' }] },
 { type: 'checkbox', checked: true, runs: [{ text: 'Install pytest' }] },
 { type: 'choice', id: 'feel', question: 'How did it go?', options: [{ id: 'easy', text: 'Easy' }, { id: 'hard', text: 'Hard' }], selected: 'hard' },
] };
const element = (html: string) => { const div = document.createElement('div'); div.innerHTML = html; return div; };

beforeEach(() => { document.execCommand = vi.fn(() => true); });
afterEach(() => vi.useRealTimers());

it('round-trips the saved document through the editor without loss', () => {
 expect(fromElement(element(toHtml(doc)))).toEqual(doc);
});

it('escapes everything typed or saved, so text is never markup', () => {
 const html = toHtml({ blocks: [{ type: 'paragraph', runs: [{ text: '<img src=x onerror=alert(1)>' }] }] });
 expect(html).not.toContain('<img');
 expect(fromElement(element(html)).blocks[0]).toEqual({ type: 'paragraph', runs: [{ text: '<img src=x onerror=alert(1)>' }] });
});

it('reduces unknown markup to paragraphs with only bold, italic and underline', () => {
 const read = fromElement(element('<div><span style="font-weight:700;color:red">Loud</span> <a href="https://x.test">link</a></div><table><tr><td>cell</td></tr></table>'));
 expect(read.blocks).toEqual([{ type: 'paragraph', runs: [{ text: 'Loud', bold: true }, { text: ' link' }] }, { type: 'paragraph', runs: [{ text: 'cell' }] }]);
});

it('offers a toolbar at the top that inserts a checkbox and a choice, then saves the document', async () => {
 vi.useFakeTimers();
 const save = vi.fn(async () => true);
 render(<NotesEditor label="Notes for Unit tests" value={null} onSave={save}/>);
 const toolbar = screen.getByRole('toolbar', { name: 'Format Notes for Unit tests' });
 for (const name of ['Bold', 'Italic', 'Underline', 'Heading', 'Bulleted list', 'Numbered list', 'Insert checkbox', 'Insert choice']) expect(screen.getByRole('button', { name })).toBeInTheDocument();
 expect(toolbar.compareDocumentPosition(screen.getByRole('textbox', { name: 'Notes for Unit tests' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 fireEvent.click(screen.getByRole('button', { name: 'Insert checkbox' }));
 fireEvent.click(screen.getByRole('button', { name: 'Insert choice' }));
 expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes');
 await act(async () => { vi.advanceTimersByTime(1000); });
 expect(save).toHaveBeenCalledOnce();
 const saved = (save.mock.calls[0] as unknown as [NotesDocument])[0];
 expect(saved.blocks.map(block => block.type)).toEqual(['checkbox', 'choice']);
 const choice = saved.blocks[1] as Extract<NotesDocument['blocks'][number], { type: 'choice' }>;
 expect(choice.options.map(option => option.text)).toEqual(['Easy', 'About right', 'Hard']);
 expect(screen.getByRole('status')).toHaveTextContent('All changes saved');
});

it('keeps the text and offers a retry when saving fails', async () => {
 const save = vi.fn(async () => false);
 render(<NotesEditor label="Notes" value={doc} onSave={save}/>);
 const page = screen.getByRole('textbox', { name: 'Notes' });
 fireEvent.click(page.querySelector('input[type="radio"]')!);
 fireEvent.blur(page);
 await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Not saved'));
 expect(page).toHaveTextContent('Set up pytest today.');
 expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible();
});
