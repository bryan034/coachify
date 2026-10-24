import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { EmploymentSuggestions } from './employment-suggestions';

test('company suggestions can be selected without restricting manual names', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([{ id: 'synthetic', name: 'Synthetic suggested company' }])));
  const change = vi.fn();
  render(<EmploymentSuggestions id="company" kind="companies" label="Place of employment" value="Synthetic" onChange={change} />);
  fireEvent.focus(screen.getByRole('textbox'));
  fireEvent.click(await screen.findByRole('button', { name: 'Synthetic suggested company' }));
  expect(change).toHaveBeenCalledWith('Synthetic suggested company');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'An unlisted organisation' } });
  expect(change).toHaveBeenCalledWith('An unlisted organisation');
});

test('failed industry suggestions leave manual input available', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: 'Synthetic outage' }, { status: 503 })));
  const change = vi.fn();
  render(<EmploymentSuggestions id="industry" kind="industries" label="Industry" value="" onChange={change} />);
  fireEvent.focus(screen.getByRole('textbox'));
  await waitFor(() => expect(screen.getByText(/Suggestions are unavailable/)).toBeInTheDocument());
  expect(screen.getByRole('textbox')).toBeEnabled();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'A custom industry' } });
  expect(change).toHaveBeenCalledWith('A custom industry');
});
