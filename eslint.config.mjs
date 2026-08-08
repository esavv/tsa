import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['node_modules/**', 'templates/**'],
  },
  {
    files: ['static/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'script',
      globals: {
        ...globals.browser,
        terminalTabLabel: 'readonly',
      },
    },
    rules: js.configs.recommended.rules,
  },
];
