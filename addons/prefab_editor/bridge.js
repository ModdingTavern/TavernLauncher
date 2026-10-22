'use strict';
const readline = require('readline');
const path = require('path');
const { createServer, start } = require('./panel/server');
const { unwrapConsole } = require('./panel/lib/consolePipe');

let nextId = 0;
const pending = new Map();
function send(command) {
    return new Promise((resolve, reject) => {
        const id = ++nextId;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error('Console timed out; refresh before retrying.')); }, 30000);
        pending.set(id, { resolve, reject, timer });
        process.stdout.write(JSON.stringify({ id, command }) + '\n');
    });
}

async function main() {
    readline.createInterface({ input: process.stdin }).on('line', line => {
        try {
            const message = JSON.parse(line), request = pending.get(message.id);
            if (!request) return;
            pending.delete(message.id); clearTimeout(request.timer);
            if (message.error) return request.reject(new Error(message.error));
            const result = unwrapConsole(message.result);
            request.resolve({ ...result, ok: result.exception == null });
        } catch (error) { console.error('Invalid launcher reply: ' + error.message); }
    }).on('close', () => process.exit(0));
    const pipe = { send, host: 'TavernKeeper', port: 1760 };
    const panel = createServer({ pipe, signer: { kid: 'TavernKeeper session' },
        remoteInfoBoards: true, requireSameOrigin: true, stateDir: path.join(process.env.PREFAB_STATE, 'panel'),
        catalogFile: path.join(__dirname, 'data/prefabs.json') });
    const port = await start(panel, 0);
    const panelUrl = 'http://127.0.0.1:' + port;
    process.env.WB_PANEL_URL = panelUrl;
    process.env.WB_STATE_DIR = path.join(process.env.PREFAB_STATE, 'workbench');
    process.env.WB_IMAGES_DIR = path.join(__dirname, 'payload/PrefabEditorImages');
    const workbench = require('./workbench/server');
    await workbench.start(workbench.createServer(), process.env.PREFAB_TEST_WORKBENCH_PORT === '0' ? 0 : 1767);
    console.log(JSON.stringify({ type: 'ready', panelUrl }));
    // Parent launcher owns this process; EOF also handles launcher crashes.
    process.stdin.resume();
    process.stdin.on('end', () => process.exit(0));
}
if (require.main === module) main().catch(error => { console.error(error.message); process.exit(1); });
module.exports = { send };
