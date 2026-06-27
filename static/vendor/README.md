# Vendored address data

These JSON files power the cascading address dropdowns on the registration page
(`templates/register.html` + `static/js/address-form.js`). They are committed so the
app needs **no external network** at runtime.

| File | Source package | Contents |
|------|----------------|----------|
| `csc/countries.json` | [`country-state-city`](https://www.npmjs.com/package/country-state-city) | `[{name, iso}]` — 250 countries |
| `csc/states.json` | `country-state-city` | `{ iso: [{name, iso}] }` — states/provinces grouped by country |
| `twzip/twzip.json` | [`twzipcode-data`](https://github.com/yyc1217/twzipcode-data) | `{ 縣市: [{city: 鄉鎮市區, zip}] }` — Taiwan zip codes |

The worldwide *city* dataset (~8 MB) is intentionally **not** vendored: non-Taiwan
cities use a free-text field, while Taiwan gets the full 鄉鎮市區 + zip cascade.

## Refreshing the data

From this `static/vendor/` directory:

```bash
npm install country-state-city twzipcode-data
node gen_vendor.js
```

`gen_vendor.js` (committed here) reads `country-state-city/lib/assets/{country,state}.json`
and `twzipcode-data/dist/zh-tw/zipcodes.js`, slims them to the shapes above, and rewrites
the JSON files. (Slimming keeps these files at ~210 KB total instead of ~8 MB.)
`node_modules/` is git-ignored — only the generated JSON is committed.
