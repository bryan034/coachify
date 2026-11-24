import { execFile } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { resolve } from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);
const inboxScript = resolve(__dirname, '../../../../infrastructure/testing/gmail_test_inbox.py');

export function gmailTestMailbox() {
  const address = process.env.ELO_TEST_GMAIL_ADDRESS?.trim().toLowerCase();
  const appPassword = process.env.ELO_TEST_GMAIL_APP_PASSWORD?.trim();
  if (!address || !/^[a-z0-9]+(?:\.[a-z0-9]+)*@gmail\.com$/.test(address) || !appPassword) {
    throw new Error('Set ELO_TEST_GMAIL_ADDRESS and ELO_TEST_GMAIL_APP_PASSWORD for a dedicated Gmail mailbox.');
  }
  return { address, appPassword };
}

export function gmailTestRecipient(address: string) {
  return address.replace('@gmail.com', `+elo-${randomBytes(12).toString('hex')}@gmail.com`);
}

export async function gmailVerificationCode(mailbox: ReturnType<typeof gmailTestMailbox>, recipient: string) {
  const { stdout } = await run('python3', [inboxScript, recipient], {
    env: {
      PATH: process.env.PATH,
      NODE_ENV: 'test',
      ELO_TEST_GMAIL_ADDRESS: mailbox.address,
      ELO_TEST_GMAIL_APP_PASSWORD: mailbox.appPassword,
    },
    timeout: 75_000,
    maxBuffer: 4096,
    encoding: 'utf8',
  }).catch(() => {
    throw new Error('Could not read the Elo verification code from Gmail. Check the App Password, IMAP access, and SMTP delivery.');
  });
  const code = stdout.trim();
  if (!/^[0-9]{6}$/.test(code)) throw new Error('The Gmail inbox reader returned an invalid verification code.');
  return code;
}
