import nextTypescript from 'eslint-config-next/typescript';
import nextVitals from 'eslint-config-next/core-web-vitals';

const parser = nextTypescript.find(config => config.languageOptions?.parser).languageOptions.parser;
const hooks = nextVitals.find(config => config.plugins?.['react-hooks']).plugins['react-hooks'];

export default [{
  files: ['src/features/cv-ingestion/**/*.{ts,tsx}', 'src/lib/api/cv.ts'],
  ignores: ['**/*.test.*'],
  languageOptions: { parser },
  plugins: { 'react-hooks': hooks },
  linterOptions: { noInlineConfig: true },
  rules: {
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',
    'no-restricted-syntax': ['error',
      {
        selector: 'CallExpression[callee.property.name=/^querySelector(All)?$/] > Literal[value=/data-unsaved|aria-busy/]',
        message: 'Read draft and pending state from React instead of DOM attributes.',
      },
      {
        selector: 'CallExpression[callee.property.name=/^(startsWith|includes)$/][callee.object.property.name=/^(error|message|text)$/]',
        message: 'Use structured conversation state and error codes.',
      },
      {
        selector: 'CallExpression[callee.name=useEffect] CallExpression[callee.object.name=cvApi][callee.property.name=/^(select|saveCvProfile|saveSkillsProfile|delete|upload|rename)$/]',
        message: 'Keep CV mutations in explicit user actions or backend lifecycle handlers.',
      },
      {
        selector: 'LogicalExpression[operator="??"][right.raw=/^[0-9]+$/] :matches(MemberExpression[object.name=/^(policy|limits)$/], MemberExpression[object.property.name=/^(policy|limits)$/])',
        message: 'Use the API-provided limit once its response is available.',
      },
      {
        selector: 'Literal[regex.pattern=/a-f0-9.*(8|32)/]',
        message: 'The CV service sanitizes internal reference IDs before returning conversation prose.',
      },
    ],
  },
}];
