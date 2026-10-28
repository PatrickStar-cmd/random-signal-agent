/* Run the same browser-script checks locally and in deployment CI. */
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const root = path.resolve(__dirname, '..');
const logs = path.join(root, 'logs/communications-v0410');
fs.mkdirSync(logs, {recursive: true});
const entries = [];
const output = [];
function run(name, args) {
  const result = spawnSync(process.execPath, args, {cwd: root, encoding: 'utf8', timeout: 30000});
  const passed = result.status === 0;
  entries.push({name, status: passed ? 'passed' : 'failed'});
  output.push((passed ? 'PASS ' : 'FAIL ') + name, result.stdout || '', result.stderr || '', result.error?.message || '');
}
const files = fs.readdirSync(path.join(root, 'web')).filter(name => name.endsWith('.js')).sort();
for (const file of files) run('syntax: ' + file, ['--check', path.join('web', file)]);
run('alignment regression', ['scripts/test_communications_alignment.js']);
run('learning UI lifecycle regression', ['scripts/test_communications_learning_ui.js']);
run('experiment UI lifecycle regression', ['scripts/test_communications_experiments_ui.js']);
run('spatial UI lifecycle regression', ['scripts/test_communications_spatial_ui.js']);
run('waveform UI lifecycle regression', ['scripts/test_communications_waveform_ui.js']);
run('v0.4.9 experiment UI regression', ['scripts/test_communications_v049_ui.js']);
for (const file of fs.readdirSync(path.join(root, 'scripts')).filter(name => /v0410.*(?:ui)?\.js$/.test(name)).sort()) run(file, ['scripts/'+file]);
const report = {
  status: entries.every(entry => entry.status === 'passed') ? 'passed' : 'failed',
  node: process.version,
  syntax_files: files.length,
  checks: entries,
};
const text = output.filter(Boolean).join('\n');
fs.writeFileSync(path.join(logs, 'node-tests.log'), text + '\n');
fs.writeFileSync(path.join(logs, 'verification-ui.json'), JSON.stringify(report, null, 2) + '\n');
console.log(text);
if (report.status !== 'passed') process.exitCode = 1;
