#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Generate development config.json
const devConfig = {
    API_URL: process.env.VITE_API_URL || "http://localhost:8000",
    SUPABASE_URL: process.env.VITE_SUPABASE_URL || "",
    SUPABASE_ANON_KEY: process.env.VITE_SUPABASE_ANON_KEY || ""
};

if (!devConfig.SUPABASE_URL || !devConfig.SUPABASE_ANON_KEY) {
    throw new Error('Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY before running setup:dev');
}

const configPath = path.resolve(__dirname, '../public/config.json');
fs.writeFileSync(configPath, JSON.stringify(devConfig, null, 2));

console.log('✅ Generated development config.json');
console.log('📍 Location:', configPath);
console.log('🔗 API URL:', devConfig.API_URL);
