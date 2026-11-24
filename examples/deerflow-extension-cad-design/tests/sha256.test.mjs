import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import test from "node:test";

import { sha256Hex } from "../ui/sha256.js";

const reference = (bytes) => createHash("sha256").update(bytes).digest("hex");

test("the standard vectors", () => {
  const ascii = (text) => new TextEncoder().encode(text);
  assert.equal(
    sha256Hex(new Uint8Array()),
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  );
  assert.equal(
    sha256Hex(ascii("abc")),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
  assert.equal(
    sha256Hex(
      ascii("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
    ),
    "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
  );
});

test("every length around the padding boundaries matches node:crypto", () => {
  // 55, 56 and 64 bytes are where the length field moves to a second block.
  for (const length of [
    1, 54, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 129, 1000,
  ]) {
    const bytes = randomBytes(length);
    assert.equal(sha256Hex(bytes), reference(bytes), `length ${length}`);
  }
});

test("a multi-megabyte buffer, the size of the shipped wasm, matches node:crypto", () => {
  const bytes = randomBytes(9 * 1024 * 1024 + 3);
  assert.equal(sha256Hex(bytes), reference(bytes));
});
