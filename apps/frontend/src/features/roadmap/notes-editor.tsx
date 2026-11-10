"use client";
import { useEffect, useRef, useState } from 'react';
import type { NoteBlock, NoteRun, NotesDocument } from './types';

/*
 * A Word-like notes page. People type freely; the toolbar formats text and inserts a
 * checkbox or a single-choice question at the cursor. What is saved is a small,
 * validated document (see NotesDocument), never the editor's HTML, so pasted markup
 * is reduced to plain text with bold, italic and underline.
 */

const escape = (value: string) => value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
const uid = () => Math.random().toString(36).slice(2, 10);
const MAX_TEXT = 20000;

function runsHtml(runs: NoteRun[]) {
 const html = runs.map(run => { let text = escape(run.text); if (run.bold) text = `<b>${text}</b>`; if (run.italic) text = `<i>${text}</i>`; if (run.underline) text = `<u>${text}</u>`; return text; }).join('');
 return html || '<br>';
}

/** The saved document as editor HTML. Every piece of text is escaped. */
export function toHtml(doc: NotesDocument | null | undefined) {
 const blocks = doc?.blocks.length ? doc.blocks : [{ type: 'paragraph', runs: [] } as NoteBlock];
 let html = '', list: 'ul' | 'ol' | null = null;
 const close = () => { if (list) { html += `</${list}>`; list = null; } };
 for (const block of blocks) {
  if (block.type === 'bullet' || block.type === 'numbered') {
   const tag = block.type === 'bullet' ? 'ul' : 'ol';
   if (list !== tag) { close(); html += `<${tag}>`; list = tag; }
   html += `<li>${runsHtml(block.runs)}</li>`; continue;
  }
  close();
  if (block.type === 'heading') html += `<h3>${runsHtml(block.runs)}</h3>`;
  else if (block.type === 'paragraph') html += `<p>${runsHtml(block.runs)}</p>`;
  else if (block.type === 'checkbox') html += `<div class="note-check" data-note="checkbox"><input type="checkbox" contenteditable="false" aria-label="Done"${block.checked ? ' checked' : ''}><span>${runsHtml(block.runs)}</span></div>`;
  else if (block.type === 'choice') html += `<fieldset class="note-choice" data-note="choice" data-id="${escape(block.id)}"><legend>${escape(block.question) || '<br>'}</legend>${block.options.map(option => `<label data-id="${escape(option.id)}"><input type="radio" contenteditable="false" name="choice-${escape(block.id)}"${block.selected === option.id ? ' checked' : ''}><span>${escape(option.text) || '<br>'}</span></label>`).join('')}</fieldset>`;
 }
 close();
 return html;
}

function runsOf(node: Node, marks: Omit<NoteRun, 'text'> = {}): NoteRun[] {
 if (node.nodeType === Node.TEXT_NODE) { const text = node.textContent ?? ''; return text ? [{ text, ...marks }] : []; }
 if (!(node instanceof HTMLElement) || node instanceof HTMLInputElement) return [];
 const tag = node.tagName;
 const style = node.style;
 const next = { ...marks,
  ...(tag === 'B' || tag === 'STRONG' || Number(style.fontWeight) >= 600 || style.fontWeight === 'bold' ? { bold: true } : {}),
  ...(tag === 'I' || tag === 'EM' || style.fontStyle === 'italic' ? { italic: true } : {}),
  ...(tag === 'U' || style.textDecoration.includes('underline') ? { underline: true } : {}) };
 if (tag === 'BR') return [];
 return [...node.childNodes].flatMap(child => runsOf(child, next));
}
/** Adjacent runs with the same marks become one; mark flags are only kept when set. */
function tidy(runs: NoteRun[]): NoteRun[] {
 const out: NoteRun[] = [];
 for (const run of runs) {
  const clean: NoteRun = { text: run.text, ...(run.bold ? { bold: true } : {}), ...(run.italic ? { italic: true } : {}), ...(run.underline ? { underline: true } : {}) };
  const last = out[out.length - 1];
  if (last && !!last.bold === !!clean.bold && !!last.italic === !!clean.italic && !!last.underline === !!clean.underline) last.text += clean.text;
  else out.push(clean);
 }
 return out.map(run => ({ ...run, text: run.text.slice(0, 2000) }));
}

/** Reads the editor back into the document format. Unknown markup becomes plain paragraphs. */
export function fromElement(root: HTMLElement): NotesDocument {
 const blocks: NoteBlock[] = [];
 const visit = (node: Node) => {
  if (node.nodeType === Node.TEXT_NODE) { if (node.textContent?.trim()) blocks.push({ type: 'paragraph', runs: tidy(runsOf(node)) }); return; }
  if (!(node instanceof HTMLElement)) return;
  const kind = node.dataset.note, tag = node.tagName;
  if (kind === 'checkbox') { const box = node.querySelector('input'); blocks.push({ type: 'checkbox', checked: !!box?.checked, runs: tidy(runsOf(node.querySelector('span') ?? node)) }); return; }
  if (kind === 'choice') {
   const options = [...node.querySelectorAll('label')].map(label => ({ id: label.dataset.id || uid(), text: (label.textContent ?? '').trim().slice(0, 200), checked: !!label.querySelector('input')?.checked }));
   if (options.length >= 2) blocks.push({ type: 'choice', id: node.dataset.id || uid(), question: (node.querySelector('legend')?.textContent ?? '').trim().slice(0, 500), options: options.slice(0, 8).map(({ id, text }) => ({ id, text })), selected: options.find(option => option.checked)?.id ?? null });
   return;
  }
  if (tag === 'UL' || tag === 'OL') { for (const item of node.children) if (item.tagName === 'LI') blocks.push({ type: tag === 'UL' ? 'bullet' : 'numbered', runs: tidy(runsOf(item)) }); return; }
  if (/^H[1-6]$/.test(tag)) { blocks.push({ type: 'heading', runs: tidy(runsOf(node)) }); return; }
  if (tag === 'P' || tag === 'DIV') {
   // Browsers wrap new lines in DIVs; a DIV holding block children is a container.
   if ([...node.children].some(child => ['P', 'DIV', 'UL', 'OL', 'H3', 'FIELDSET'].includes(child.tagName))) { node.childNodes.forEach(visit); return; }
   blocks.push({ type: 'paragraph', runs: tidy(runsOf(node)) }); return;
  }
  blocks.push({ type: 'paragraph', runs: tidy(runsOf(node)) });
 };
 root.childNodes.forEach(visit);
 // Empty paragraphs at the start or end are not content; blank lines in between are kept.
 const empty = (block?: NoteBlock) => !!block && block.type === 'paragraph' && !block.runs.some(run => run.text.trim());
 while (empty(blocks[blocks.length - 1])) blocks.pop();
 while (empty(blocks[0])) blocks.shift();
 return { blocks: blocks.slice(0, 300) };
}

const textLength = (doc: NotesDocument) => doc.blocks.reduce((total, block) => total + ('runs' in block ? block.runs.reduce((n, run) => n + run.text.length, 0) : block.question.length + block.options.reduce((n, option) => n + option.text.length, 0)), 0);

function insertAtCaret(root: HTMLElement, html: string) {
 const selection = window.getSelection();
 const range = selection && selection.rangeCount && root.contains(selection.getRangeAt(0).commonAncestorContainer) ? selection.getRangeAt(0) : null;
 const holder = document.createElement('div'); holder.innerHTML = html;
 const nodes = [...holder.childNodes];
 if (!range) { nodes.forEach(node => root.appendChild(node)); return; }
 // Insert after the block that holds the caret, so a checkbox never lands mid-sentence.
 let block: Node | null = range.startContainer;
 while (block && block.parentNode !== root) block = block.parentNode;
 const anchor = block?.nextSibling ?? null;
 nodes.forEach(node => root.insertBefore(node, anchor));
}

type Tool = { label: string; text: string; run: () => void; pressed?: string };

export function NotesEditor({ value, label, disabled = false, onSave }: { value: NotesDocument | null | undefined; label: string; disabled?: boolean; onSave: (doc: NotesDocument) => Promise<unknown> }) {
 const editor = useRef<HTMLDivElement>(null);
 const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
 const savedJson = useRef(JSON.stringify(value ?? { blocks: [] }));
 const [state, setState] = useState<'saved' | 'saving' | 'unsaved' | 'failed' | 'too_long'>('saved');
 // The editor owns its DOM while open; it is only reset when the saved notes change elsewhere.
 useEffect(() => { if (editor.current && document.activeElement !== editor.current) { editor.current.innerHTML = toHtml(value); savedJson.current = JSON.stringify(value ?? { blocks: [] }); } }, [value]);
 useEffect(() => () => clearTimeout(timer.current), []);
 const save = async () => {
  if (!editor.current) return;
  const doc = fromElement(editor.current), json = JSON.stringify(doc);
  if (json === savedJson.current) { setState('saved'); return; }
  if (textLength(doc) > MAX_TEXT) { setState('too_long'); return; }
  setState('saving');
  const ok = await onSave(doc);
  if (ok === false) { setState('failed'); return; }
  savedJson.current = json; setState('saved');
 };
 const changed = () => { setState('unsaved'); clearTimeout(timer.current); timer.current = setTimeout(() => void save(), 900); };
 const command = (name: string, arg?: string) => { editor.current?.focus(); document.execCommand(name, false, arg); changed(); };
 const insert = (html: string) => { if (!editor.current) return; editor.current.focus(); insertAtCaret(editor.current, html); changed(); };
 const tools: Tool[][] = [
  [{ label: 'Bold', text: 'B', run: () => command('bold'), pressed: 'bold' }, { label: 'Italic', text: 'I', run: () => command('italic'), pressed: 'italic' }, { label: 'Underline', text: 'U', run: () => command('underline'), pressed: 'underline' }],
  [{ label: 'Heading', text: 'Heading', run: () => command('formatBlock', 'h3') }, { label: 'Bulleted list', text: '• List', run: () => command('insertUnorderedList') }, { label: 'Numbered list', text: '1. List', run: () => command('insertOrderedList') }],
  [{ label: 'Insert checkbox', text: '☐ Checkbox', run: () => insert(toHtml({ blocks: [{ type: 'checkbox', checked: false, runs: [] }] })) },
   { label: 'Insert choice', text: '◉ Choice', run: () => insert(toHtml({ blocks: [{ type: 'choice', id: uid(), question: 'How did it go?', options: [{ id: uid(), text: 'Easy' }, { id: uid(), text: 'About right' }, { id: uid(), text: 'Hard' }], selected: null }] })) }],
 ];
 const status = { saved: 'All changes saved', saving: 'Saving…', unsaved: 'Unsaved changes', failed: 'Not saved. Keep typing or try again.', too_long: `Notes can hold up to ${MAX_TEXT.toLocaleString('en-GB')} characters.` }[state];
 return <div className="notes-editor">
  <div className="notes-toolbar" role="toolbar" aria-label={`Format ${label}`}>
   {tools.map((group, index) => <div className="notes-tool-group" key={index}>{group.map(tool => <button key={tool.label} type="button" aria-label={tool.label} title={tool.label} disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={tool.run}>{tool.text}</button>)}</div>)}
   {state === 'failed' && <button type="button" className="btn ghost sm" onClick={() => void save()}>Try again</button>}
  </div>
  <div ref={editor} className="notes-page" role="textbox" aria-multiline="true" aria-label={label} contentEditable={!disabled} suppressContentEditableWarning
   onInput={changed} onBlur={() => { clearTimeout(timer.current); void save(); }}
   onClick={event => { if ((event.target as HTMLElement).tagName === 'INPUT') changed(); }}
   onPaste={event => { event.preventDefault(); document.execCommand('insertText', false, event.clipboardData.getData('text/plain')); }}/>
  <p className="small notes-status" role="status">{status}</p>
 </div>;
}
