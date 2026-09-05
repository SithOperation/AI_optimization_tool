import { defineConfig } from 'vite';

const ignored = [
  '**/src-tauri/target/**',
  '**/src-tauri/binaries/**',
  '**/artifacts/**',
  '**/.test-data/**',
  '**/test-results/**',
  '**/database/**',
  '**/.git/**',
  '**/node_modules/**',
];

export default defineConfig({
  server: {
    host: '0.0.0.0',
    watch: {
      ignored,
    },
  },
});
