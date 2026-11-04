// Display-only filtering also covers replies saved by older backend versions.
export function reviewText(text: string, sourceIds: string[] = []): string {
 const uuid = '[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}';
 const id = `(?:${uuid}|[a-f0-9]{32,64})`;
 const reference = `(?:(?:fact|evidence|source|item):[a-f0-9]{24,64}|answer:${uuid}|${id})`;
 const label = '(?:(?:evidence|source|item|experience|ref)(?:[_ ](?:ids?|refs?))?\\s*[:=]?\\s*)?';
 const longGroup = `${label}${reference}(?:\\s*[,;]\\s*${reference})*`;
 const shortGroup = '(?:evidence|source|item|ref)(?:[_ ](?:ids?|refs?))?\\s*[:=]?\\s*b\\d+';
 const group = `(?:${longGroup}|${shortGroup})`;
 let visible = text.replace(new RegExp(`\\s*\\[\\s*${group}\\s*\\]`, 'gi'), '')
  .replace(new RegExp(`\\s*\\(\\s*${group}\\s*\\)`, 'gi'), '')
  .replace(/\s*\[\s*b\d+\s*\]/g, '')
  .replace(new RegExp(`\\b(?:evidence|source|item)[_ ](?:ids?|refs?)\\s*[:=]\\s*(?:${reference}|b\\d+)`, 'gi'), '')
  .replace(new RegExp(`\\b(?:(?:fact|evidence|source|item):[a-f0-9]{24,64}|answer:${uuid})\\b`, 'gi'), '');
 for (const sourceId of sourceIds) {
  if (!new RegExp(`^${id}$`, 'i').test(sourceId)) continue;
  visible = visible.replace(new RegExp(`\\b${sourceId}\\b`, 'gi'), '');
 }
 return visible.replace(/\s*[\[(]\s*[\])]/g, '').replace(/ {2,}/g, ' ').replace(/ +([,.;:!?])/g, '$1').trim();
}
