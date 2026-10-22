import { spawn } from 'node:child_process';

// A small stdio client keeps devnet setup, transactions and cleanup in one owner.
export class DevnetClient {
  #next = 0;
  #pending = new Map();
  #process;

  constructor() {
    this.#process = spawn('casper-devnet', ['mcp', '--transport', 'stdio'], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.#process.stderr.on('data', data => {
      if (process.env.DEVNET_VERBOSE) process.stderr.write(data);
    });
    let buffer = '';
    this.#process.stdout.on('data', data => {
      buffer += data;
      for (;;) {
        const newline = buffer.indexOf('\n');
        if (newline < 0) break;
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        if (!line.trim()) continue;
        const message = JSON.parse(line);
        const pending = this.#pending.get(message.id);
        if (!pending) continue;
        this.#pending.delete(message.id);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else pending.resolve(message.result);
      }
    });
    this.#process.on('error', error => this.#fail(error));
    this.#process.on('exit', (code, signal) => {
      this.#fail(new Error(`casper-devnet exited (${code ?? signal})`));
    });
  }

  #fail(error) {
    for (const pending of this.#pending.values()) pending.reject(error);
    this.#pending.clear();
  }

  request(method, params = {}) {
    const id = ++this.#next;
    return new Promise((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
      this.#process.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }

  async initialize() {
    await this.request('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'casthon-py-counter-poc', version: '0.1.0' },
    });
    this.#process.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  }

  async call(name, args = {}) {
    const response = await this.request('tools/call', { name, arguments: args });
    if (response.isError) throw new Error(`${name}: ${JSON.stringify(response.content)}`);
    const content = response.content?.filter(item => item.type === 'text').map(item => item.text).join('\n');
    return response.structuredContent ?? (content ? JSON.parse(content) : response);
  }

  close() {
    this.#process.stdin.end();
  }
}
