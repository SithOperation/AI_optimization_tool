import { defineConfig } from 'vite';

const ignored = [
  '**/src-tauri/target/**',
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
