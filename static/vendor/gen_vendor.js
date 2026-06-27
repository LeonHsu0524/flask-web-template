/*
 * Regenerate the vendored address data in this folder.
 *
 * Usage (from this directory):
 *   npm install country-state-city twzipcode-data
 *   node gen_vendor.js
 *
 * Reads the two upstream packages from ./node_modules and writes slimmed JSON
 * (~210 KB total) next to this script.
 */
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const CSC = path.join(HERE, "node_modules/country-state-city/lib/assets");

// 1) Countries -> [{name, iso}] sorted by name
const countries = JSON.parse(fs.readFileSync(path.join(CSC, "country.json"), "utf8"))
  .map((c) => ({ name: c.name, iso: c.isoCode }))
  .sort((a, b) => a.name.localeCompare(b.name));
fs.mkdirSync(path.join(HERE, "csc"), { recursive: true });
fs.writeFileSync(path.join(HERE, "csc/countries.json"), JSON.stringify(countries));

// 2) States grouped by country iso -> { "US": [{name, iso}], ... }
const statesArr = JSON.parse(fs.readFileSync(path.join(CSC, "state.json"), "utf8"));
const states = {};
for (const s of statesArr) (states[s.countryCode] ||= []).push({ name: s.name, iso: s.isoCode });
for (const k of Object.keys(states)) states[k].sort((a, b) => a.name.localeCompare(b.name));
fs.writeFileSync(path.join(HERE, "csc/states.json"), JSON.stringify(states));

// 3) Taiwan zipcodes -> { "臺北市": [{city, zip}], ... } (source order preserved)
const zips = require(path.join(HERE, "node_modules/twzipcode-data/dist/zh-tw/zipcodes.js"));
const tw = {};
for (const z of zips) (tw[z.county] ||= []).push({ city: z.city, zip: String(z.zipcode) });
fs.mkdirSync(path.join(HERE, "twzip"), { recursive: true });
fs.writeFileSync(path.join(HERE, "twzip/twzip.json"), JSON.stringify(tw));

console.log("countries:", countries.length, "| states for", Object.keys(states).length,
  "countries | TW counties:", Object.keys(tw).length);
