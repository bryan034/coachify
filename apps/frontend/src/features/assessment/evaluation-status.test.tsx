import { render, screen, fireEvent } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { Comparison } from './comparison';
import type { EvaluationStatus } from '@/lib/api/assessment';
import { EvaluationStatusPanel } from './evaluation-status';

function comparison(status: Partial<EvaluationStatus> = {}, extra = {}): Comparison {
 return { current: { evaluation: { freshness: 'current', processing: 'idle', completeness: 'complete', evaluated_at: '2030-01-09T00:00:00Z', reasons: [], ...status }, operation: null },
  context: { ready: true, model_available: true, cv_reviewed: true }, error: '', busy: false, compare: vi.fn(), retry: vi.fn(), ...extra } as unknown as Comparison;
}
it('shows a current saved evaluation and offers no unnecessary evaluation command', () => {
 render(<EvaluationStatusPanel comparison={comparison()} actions />);
 expect(screen.getByText('Skill evaluation: Up to date')).toBeVisible();
 expect(screen.getByText(/Last evaluated/)).toBeVisible();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('labels outdated partial data while its replacement is processing', () => {
 render(<EvaluationStatusPanel comparison={comparison({ freshness: 'outdated', processing: 'evaluating', completeness: 'partial', reasons: ['cv_changed'] })} actions />);
 expect(screen.getByText('Skill evaluation: Outdated')).toBeVisible();
 expect(screen.getByText(/Partial evaluation/)).toBeVisible();
 expect(screen.getByText('Your selected CV or its contents changed.')).toBeVisible();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('starts evaluation only through the explicit command', () => {
 const c = comparison({freshness: 'missing', evaluated_at: null, completeness: null});
 render(<EvaluationStatusPanel comparison={c} actions />);
 expect(c.compare).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button', {name: 'Evaluate skills'}));
 expect(c.compare).toHaveBeenCalledOnce();
});
it('does not label cached data current after a failed source check', () => {
 const c = comparison({}, {error: 'Could not read sources.'});
 render(<EvaluationStatusPanel comparison={c} actions />);
 expect(screen.getByText('Skill evaluation: Unable to verify')).toBeVisible();
 expect(screen.queryByText('Skill evaluation: Up to date')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', {name: 'Check evaluation'}));
 expect(c.retry).toHaveBeenCalledOnce();
});
