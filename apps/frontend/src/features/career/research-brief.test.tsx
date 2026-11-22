import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { SourceList } from './research-brief';
import type { BriefSource } from '@/lib/api/career';

it('only makes validated HTTP sources clickable', () => {
 const sources = ['javascript:alert(1)', '//attacker.test', 'https://credential@attacker.test', 'https://example.test/report'].map((url, index) => ({ index: index + 1, url, title: `Source ${index}`, domain: 'example.test' })) as BriefSource[];
 render(<SourceList sources={sources}/>);
 expect(screen.getAllByRole('link')).toHaveLength(1);
 expect(screen.getByRole('link')).toHaveAttribute('href', 'https://example.test/report');
});
