import {createContext, useContext, useLayoutEffect} from 'react';

export type DraftState = {dirty: boolean; busy: boolean; itemEditor: boolean};
export const CvDrafts = createContext<Map<symbol, DraftState> | null>(null);

export function useCvDraft(dirty: boolean, busy: boolean, itemEditor = false) {
 const drafts = useContext(CvDrafts);
 useLayoutEffect(() => {
  if (!drafts || (!dirty && !busy)) return;
  const key = Symbol();
  drafts.set(key, {dirty, busy, itemEditor});
  return () => {drafts.delete(key);};
 }, [drafts, dirty, busy, itemEditor]);
}
