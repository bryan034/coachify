import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { beforeEach, afterEach } from 'vitest';

afterEach(cleanup);

beforeEach(() => {
 sessionStorage.clear(); localStorage.clear();
 localStorage.setItem('elo.access-epoch', '1');
 sessionStorage.setItem('elo.session', JSON.stringify({token:'synthetic-session-token',epoch:'1'}));
});
