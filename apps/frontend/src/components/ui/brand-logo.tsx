/** The supplied Elo artwork; the compact version uses its original symbol. */
export function BrandLogo({ compact = false, decorative = false }: { compact?: boolean; decorative?: boolean }) {
 return <img className={compact ? 'brand-symbol' : 'brand-logo'} src={`/brand/elo-${compact ? 'mark' : 'logo'}.svg`} alt={decorative ? '' : 'Elo'} width={compact ? 34 : 116} height={40} />;
}
