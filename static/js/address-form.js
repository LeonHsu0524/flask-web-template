/*
 * address-form.js — cascading address dropdowns for the registration page.
 *
 * Data sources (vendored under static/vendor/, no external network needed):
 *   - country-state-city : worldwide countries + states  (csc/countries.json, csc/states.json)
 *   - twzipcode-data     : Taiwan 縣市 → 鄉鎮市區 → 郵遞區號 (twzip/twzip.json)
 *
 * Behaviour:
 *   - Country dropdown is always shown.
 *   - Taiwan: the "state" select becomes the 縣市 picker, a 鄉鎮市區 (district)
 *     select appears, and the zipcode auto-fills (read-only).
 *   - Other countries: the "state" select lists that country's states/provinces,
 *     and city + zipcode become free-text (worldwide city/zip data is not bundled).
 *   - The street/detail field is always free-text.
 *
 * Every field submits natively via its name=, so the server just reads the form.
 * The script no-ops if the address section is absent (feature disabled by config).
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var country = document.getElementById("addr-country");
    if (!country) return; // address section disabled — nothing to wire.

    var base = country.getAttribute("data-vendor-base"); // e.g. /static/vendor
    var state = document.getElementById("addr-state");
    var districtGroup = document.getElementById("addr-district-group");
    var district = document.getElementById("addr-district");
    var cityGroup = document.getElementById("addr-city-group");
    var zipcode = document.getElementById("addr-zipcode");

    var statesCache = null; // { iso: [{name, iso}] }
    var twCache = null;     // { county: [{city, zip}] }

    function getJSON(url) {
      return fetch(url, { credentials: "same-origin" }).then(function (r) {
        if (!r.ok) throw new Error("Failed to load " + url);
        return r.json();
      });
    }

    function clearSelect(sel, placeholder) {
      sel.innerHTML = "";
      var opt = document.createElement("option");
      opt.value = "";
      opt.textContent = placeholder;
      sel.appendChild(opt);
    }

    function addOption(sel, value, text, iso) {
      var opt = document.createElement("option");
      opt.value = value;
      opt.textContent = text;
      if (iso != null) opt.setAttribute("data-iso", iso);
      sel.appendChild(opt);
    }

    function selectedIso(sel) {
      var o = sel.options[sel.selectedIndex];
      return o ? o.getAttribute("data-iso") : null;
    }

    // --- Taiwan path ---------------------------------------------------------
    function showTaiwan() {
      if (districtGroup) districtGroup.style.display = "";
      if (cityGroup) cityGroup.style.display = "none";
      if (zipcode) { zipcode.readOnly = true; zipcode.value = ""; }

      var fill = function () {
        clearSelect(state, "請選擇縣市");
        Object.keys(twCache).forEach(function (county) {
          addOption(state, county, county);
        });
        clearSelect(district, "請選擇鄉鎮市區");
      };
      if (twCache) { fill(); }
      else {
        getJSON(base + "/twzip/twzip.json").then(function (data) {
          twCache = data; fill();
        });
      }
    }

    function onTaiwanCounty() {
      clearSelect(district, "請選擇鄉鎮市區");
      var list = (twCache && twCache[state.value]) || [];
      list.forEach(function (d) { addOption(district, d.city, d.city + " (" + d.zip + ")"); });
      if (zipcode) zipcode.value = "";
    }

    function onTaiwanDistrict() {
      var list = (twCache && twCache[state.value]) || [];
      var hit = list.find(function (d) { return d.city === district.value; });
      if (zipcode) zipcode.value = hit ? hit.zip : "";
    }

    // --- International path ---------------------------------------------------
    function showInternational(iso) {
      if (districtGroup) districtGroup.style.display = "none";
      if (cityGroup) cityGroup.style.display = "";
      if (zipcode) zipcode.readOnly = false;

      var fill = function () {
        clearSelect(state, "請選擇 Select state / province");
        var list = (statesCache && statesCache[iso]) || [];
        list.forEach(function (s) { addOption(state, s.name, s.name, s.iso); });
      };
      if (statesCache) { fill(); }
      else {
        getJSON(base + "/csc/states.json").then(function (data) {
          statesCache = data; fill();
        });
      }
    }

    // --- Wiring --------------------------------------------------------------
    function onCountryChange() {
      var iso = selectedIso(country);
      if (!iso) { clearSelect(state, "—"); return; }
      if (iso === "TW") showTaiwan();
      else showInternational(iso);
    }

    country.addEventListener("change", onCountryChange);
    state.addEventListener("change", function () {
      if (selectedIso(country) === "TW") onTaiwanCounty();
    });
    if (district) district.addEventListener("change", onTaiwanDistrict);

    // Populate countries, default to Taiwan (zh-TW audience), then cascade.
    getJSON(base + "/csc/countries.json").then(function (list) {
      clearSelect(country, "請選擇國家/地區 Select country");
      list.forEach(function (c) { addOption(country, c.name, c.name, c.iso); });
      var tw = Array.prototype.find.call(country.options, function (o) {
        return o.getAttribute("data-iso") === "TW";
      });
      if (tw) { country.value = tw.value; onCountryChange(); }
    });
  });
})();
