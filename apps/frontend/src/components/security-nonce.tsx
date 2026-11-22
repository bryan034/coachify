"use client";
import { createContext, useContext, type ReactNode } from 'react';

const Context = createContext<string | undefined>(undefined);
export const useSecurityNonce = () => useContext(Context);
export function SecurityNonceProvider({ nonce, children }: { nonce: string; children: ReactNode }) {
 return <Context.Provider value={nonce}>{children}</Context.Provider>;
}
