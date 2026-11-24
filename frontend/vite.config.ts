/** Compile Tailwind utilities alongside the existing React application styles. */
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({ plugins: [tailwindcss()] });
