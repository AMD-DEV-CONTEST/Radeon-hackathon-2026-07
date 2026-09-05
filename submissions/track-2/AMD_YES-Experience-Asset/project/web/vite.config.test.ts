// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { resolveProxyTarget } from './vite.config';

describe('local-only Vite proxy target', () => {
  it.each([
    ['http://localhost:8080', 'http://localhost:8080'],
    ['https://127.0.0.1:8443', 'https://127.0.0.1:8443'],
    ['http://[::1]:8080', 'http://[::1]:8080'],
  ])('accepts loopback origin %s', (target, expected) => {
    expect(resolveProxyTarget(target)).toBe(expected);
  });

  it.each([
    'https://api.example.com',
    'http://192.168.1.10:8080',
    'ftp://127.0.0.1:8080',
    'http://127.0.0.1:8080/api',
    'not-a-url',
  ])('rejects non-loopback or non-origin target %s', (target) => {
    expect(() => resolveProxyTarget(target)).toThrow(/loopback/);
  });
});
