import { describe, expect, test } from "bun:test";
import { combineShares, splitPhrase } from "../app/lib/shamir";

const PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";

describe("social recovery shares", () => {
  test("any 2 of 3 rebuild the phrase", () => {
    const [a, b, c] = splitPhrase(PHRASE);
    expect(combineShares([a!, b!])).toBe(PHRASE);
    expect(combineShares([a!, c!])).toBe(PHRASE);
    expect(combineShares([c!, b!])).toBe(PHRASE);
  });
  test("one share alone or mixed backups are refused", () => {
    const [a] = splitPhrase(PHRASE);
    const [, other] = splitPhrase("legal winner thank year wave sausage worth useful legal winner thank yellow");
    expect(() => combineShares([a!])).toThrow();
    expect(() => combineShares([a!, a!])).toThrow(/same share/);
    expect(() => combineShares([a!, other!])).toThrow(/different backups/);
    expect(() => combineShares(["hello", a!])).toThrow(/isn't a Satish/);
  });
  test("shares are random each time and 24 words work", () => {
    const p24 = Array(23).fill("abandon").join(" ") + " art";
    const s1 = splitPhrase(p24);
    const s2 = splitPhrase(p24);
    expect(s1[0]).not.toBe(s2[0]);
    expect(combineShares([s1[1]!, s1[2]!])).toBe(p24);
  });
});
