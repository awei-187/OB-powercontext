import path from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';
import mysql from 'mysql2/promise';

const required = ['SEEKDB_HOST', 'SEEKDB_PORT', 'SEEKDB_USER', 'SEEKDB_PASSWORD', 'SEEKDB_DATABASE'];
const missing = required.filter((name) => !process.env[name]);
if (missing.length) {
  throw new Error(`Missing server configuration: ${missing.join(', ')}. Load the project .env file.`);
}

const resultDir = process.env.RESULT_DIR || 'test-results';
const evidence = {
  startedAt: new Date().toISOString(),
  mode: 'server',
  endpoint: `${process.env.SEEKDB_HOST}:${process.env.SEEKDB_PORT}`,
  database: process.env.SEEKDB_DATABASE,
};

let connection;
try {
  connection = await mysql.createConnection({
    host: process.env.SEEKDB_HOST,
    port: Number(process.env.SEEKDB_PORT),
    user: process.env.SEEKDB_USER,
    password: process.env.SEEKDB_PASSWORD,
    database: process.env.SEEKDB_DATABASE,
    connectTimeout: 10_000,
  });
  const [[status]] = await connection.query(
    'SELECT 1 AS ready, VERSION() AS version, DATABASE() AS database_name, CURRENT_USER() AS account_name',
  );
  const [[tables]] = await connection.query(
    'SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = DATABASE()',
  );
  evidence.status = status;
  evidence.tableCount = Number(tables.table_count);
  evidence.ok = status.ready === 1;
} catch (error) {
  evidence.ok = false;
  evidence.error = error.message;
  process.exitCode = 1;
} finally {
  await connection?.end();
}

evidence.finishedAt = new Date().toISOString();
await mkdir(resultDir, { recursive: true });
const output = path.join(resultDir, 'db-server-probe.json');
await writeFile(output, `${JSON.stringify(evidence, null, 2)}\n`);
console.log(JSON.stringify({ ...evidence, output }, null, 2));
