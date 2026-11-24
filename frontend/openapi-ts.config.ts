/** Generate only the reviewed local read contract; never fetch a live schema. */
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: './openapi/reader.json',
  output: './src/api/generated',
  plugins: ['@hey-api/typescript', '@hey-api/sdk', '@hey-api/client-fetch'],
});
