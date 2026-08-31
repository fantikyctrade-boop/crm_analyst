"""Generate a standalone, offline HTML viewer for scored lead data."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

LEAD_TYPES = (
    "NO_WEBSITE",
    "INSTAGRAM_ONLY",
    "GOOGLE_MAPS_ONLY",
    "BUSINESS_SITE",
    "SOCIAL_ONLY",
    "HTTP_WEBSITE",
    "MODERN_WEBSITE",
    "UNKNOWN",
)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lead Board</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #15233c;
      --muted: #62708a;
      --line: #dfe5ee;
      --surface: #ffffff;
      --canvas: #f4f7fb;
      --navy: #172a4d;
      --blue: #3664e8;
      --high: #cf3d56;
      --high-soft: #fff0f3;
      --medium: #b36b00;
      --medium-soft: #fff7e6;
      --low: #25805e;
      --low-soft: #eaf8f2;
      --shadow: 0 16px 38px rgba(31, 48, 80, .10);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-width: 320px;
      background:
        radial-gradient(circle at 6% 0%, rgba(54, 100, 232, .10), transparent 28rem),
        var(--canvas);
      color: var(--ink);
      font: 14px/1.45 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }

    button, input, select { font: inherit; }
    button { cursor: pointer; }

    .shell {
      width: min(1880px, 100%);
      margin: 0 auto;
      padding: 28px clamp(18px, 3vw, 46px) 42px;
    }

    .hero {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 22px;
    }

    .eyebrow {
      margin: 0 0 7px;
      color: var(--blue);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .16em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      color: var(--navy);
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.05;
      letter-spacing: -.035em;
    }

    .subtitle {
      max-width: 720px;
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 15px;
    }

    .primary,
    .secondary {
      min-height: 42px;
      padding: 10px 16px;
      border-radius: 11px;
      border: 1px solid transparent;
      font-weight: 750;
      transition: transform .15s ease, box-shadow .15s ease, background .15s ease;
    }

    .primary {
      background: var(--navy);
      color: white;
      box-shadow: 0 8px 20px rgba(23, 42, 77, .18);
    }

    .secondary {
      border-color: var(--line);
      background: white;
      color: var(--ink);
    }

    .primary:hover,
    .secondary:hover { transform: translateY(-1px); }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }

    .lead-type-summary {
      margin-bottom: 16px;
      padding: 14px;
      border: 1px solid rgba(223, 229, 238, .9);
      border-radius: 16px;
      background: rgba(255, 255, 255, .88);
      box-shadow: 0 8px 24px rgba(31, 48, 80, .05);
    }

    .summary-title {
      margin: 0 0 10px;
      color: var(--navy);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: .08em;
      text-transform: uppercase;
    }

    .type-stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 8px;
    }

    .type-stat {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-width: 0;
      padding: 10px 12px;
      border: 1px solid #e6eaf1;
      border-radius: 11px;
      background: #f8faff;
    }

    .type-stat-label {
      overflow: hidden;
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: .035em;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .type-stat-value {
      color: var(--navy);
      font-size: 18px;
      font-weight: 900;
    }

    .stat {
      position: relative;
      overflow: hidden;
      min-height: 96px;
      padding: 18px 19px;
      border: 1px solid rgba(223, 229, 238, .85);
      border-radius: 16px;
      background: rgba(255, 255, 255, .92);
      box-shadow: 0 8px 24px rgba(31, 48, 80, .06);
    }

    .stat::after {
      content: "";
      position: absolute;
      right: -22px;
      bottom: -34px;
      width: 86px;
      height: 86px;
      border-radius: 50%;
      background: var(--accent, var(--blue));
      opacity: .09;
    }

    .stat-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .06em;
      text-transform: uppercase;
    }

    .stat-value {
      display: block;
      margin-top: 5px;
      color: var(--navy);
      font-size: 28px;
      font-weight: 850;
      line-height: 1;
    }

    .workspace {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }

    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .96);
    }

    .search-wrap {
      position: relative;
      flex: 1 1 380px;
      max-width: 540px;
    }

    .search-wrap svg {
      position: absolute;
      top: 50%;
      left: 13px;
      width: 18px;
      color: #7f8aa1;
      transform: translateY(-50%);
      pointer-events: none;
    }

    #search {
      width: 100%;
      height: 42px;
      padding: 0 14px 0 41px;
      border: 1px solid var(--line);
      border-radius: 11px;
      outline: none;
      background: #f8faff;
      color: var(--ink);
      transition: border-color .15s ease, box-shadow .15s ease;
    }

    #search:focus {
      border-color: #8ca8f4;
      box-shadow: 0 0 0 3px rgba(54, 100, 232, .11);
    }

    .toolbar-actions,
    .filters {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .toolbar-actions { flex-wrap: wrap; }

    .type-filter {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 42px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 11px;
      background: #f8faff;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }

    #leadTypeFilter {
      max-width: 190px;
      border: 0;
      outline: none;
      background: transparent;
      color: var(--navy);
      font-weight: 750;
    }

    .filters {
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 11px;
      background: #f5f7fb;
    }

    .filter {
      min-width: 62px;
      padding: 7px 10px;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }

    .filter.active {
      background: white;
      color: var(--navy);
      box-shadow: 0 2px 8px rgba(31, 48, 80, .10);
    }

    .table-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 9px 15px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
      color: var(--muted);
      font-size: 12px;
    }

    .table-scroll {
      max-height: calc(100vh - 300px);
      min-height: 360px;
      overflow: auto;
      scrollbar-color: #bcc6d7 transparent;
    }

    table {
      width: 100%;
      min-width: 2820px;
      border-collapse: separate;
      border-spacing: 0;
      table-layout: auto;
    }

    thead th {
      position: sticky;
      z-index: 3;
      top: 0;
      padding: 0;
      border-bottom: 1px solid #cfd7e4;
      background: #eef2f8;
      color: #526078;
      text-align: left;
      font-size: 11px;
      letter-spacing: .045em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .sort-button {
      display: flex;
      align-items: center;
      gap: 7px;
      width: 100%;
      min-height: 42px;
      padding: 10px 12px;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      font-weight: 800;
      letter-spacing: inherit;
      text-align: left;
      text-transform: inherit;
    }

    .sort-button:hover { background: rgba(54, 100, 232, .06); }
    .sort-mark { color: var(--blue); font-size: 12px; }

    tbody td {
      max-width: 270px;
      padding: 11px 12px;
      border-bottom: 1px solid #edf0f5;
      color: #34425a;
      vertical-align: top;
    }

    tbody tr:nth-child(even) { background: #fbfcfe; }
    tbody tr:hover { background: #f1f5ff; }
    tbody tr:last-child td { border-bottom: 0; }

    th:nth-child(1), td:nth-child(1) { min-width: 210px; }
    th:nth-child(2), td:nth-child(2) { min-width: 90px; }
    th:nth-child(3), td:nth-child(3) { min-width: 210px; }
    th:nth-child(4), td:nth-child(4) { min-width: 145px; }
    th:nth-child(5), td:nth-child(5) { min-width: 220px; }
    th:nth-child(6), td:nth-child(6) { min-width: 210px; }
    th:nth-child(7), td:nth-child(7) { min-width: 170px; }
    th:nth-child(8), td:nth-child(8) { min-width: 225px; }
    th:nth-child(9), td:nth-child(9),
    th:nth-child(10), td:nth-child(10) { min-width: 150px; }
    th:nth-child(11), td:nth-child(11) { min-width: 120px; }
    th:nth-child(12), td:nth-child(12) { min-width: 74px; }
    th:nth-child(13), td:nth-child(13) { min-width: 92px; }
    th:nth-child(14), td:nth-child(14) { min-width: 360px; }
    th:nth-child(15), td:nth-child(15) { min-width: 170px; }
    th:nth-child(16), td:nth-child(16) { min-width: 260px; }

    .company {
      min-width: 190px;
      color: var(--navy);
      font-weight: 780;
    }

    .muted { color: #97a0b1; }
    .wrap { white-space: normal; overflow-wrap: anywhere; }
    .nowrap { white-space: nowrap; }

    a {
      color: #2658d8;
      text-decoration: none;
      text-underline-offset: 2px;
    }

    a:hover { text-decoration: underline; }
    .link-list { display: grid; gap: 3px; }

    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 66px;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 900;
      letter-spacing: .08em;
    }

    .badge-high { background: var(--high-soft); color: var(--high); }
    .badge-medium { background: var(--medium-soft); color: var(--medium); }
    .badge-low { background: var(--low-soft); color: var(--low); }

    .type-badge {
      display: inline-flex;
      padding: 4px 8px;
      border: 1px solid #dbe3f2;
      border-radius: 7px;
      background: #f1f5ff;
      color: #294b9b;
      font-size: 10px;
      font-weight: 850;
      letter-spacing: .035em;
      white-space: nowrap;
    }

    .score {
      display: inline-grid;
      place-items: center;
      min-width: 34px;
      height: 30px;
      padding: 0 8px;
      border-radius: 9px;
      font-weight: 900;
    }

    .score-high { background: var(--high-soft); color: var(--high); }
    .score-medium { background: var(--medium-soft); color: var(--medium); }
    .score-low { background: var(--low-soft); color: var(--low); }

    .empty {
      padding: 60px 24px;
      color: var(--muted);
      text-align: center;
    }

    .footer-note {
      margin: 14px 2px 0;
      color: var(--muted);
      font-size: 11px;
      text-align: right;
    }

    @media (max-width: 1100px) {
      .hero { align-items: flex-start; flex-direction: column; }
      .toolbar { align-items: stretch; flex-direction: column; }
      .search-wrap { max-width: none; flex-basis: auto; }
      .toolbar-actions { justify-content: space-between; }
      .table-scroll { max-height: calc(100vh - 350px); }
    }

    @media (max-width: 720px) {
      .shell { padding: 20px 12px 30px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .type-stats { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
      .toolbar-actions { align-items: stretch; flex-direction: column; }
      .type-filter { justify-content: space-between; }
      .filters { overflow-x: auto; }
      .secondary { width: 100%; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">Offline lead workspace</p>
        <h1>Lead Board</h1>
        <p class="subtitle">
          Швидкий перегляд, пошук і сортування потенційних клієнтів —
          повністю локально, без сервера.
        </p>
      </div>
      <button class="primary" id="highOnly" type="button">Показати тільки HIGH</button>
    </header>

    <section class="stats" aria-label="Лічильники">
      <article class="stat" style="--accent:#3664e8">
        <span class="stat-label">Всього</span>
        <strong class="stat-value" id="countAll">0</strong>
      </article>
      <article class="stat" style="--accent:#cf3d56">
        <span class="stat-label">High</span>
        <strong class="stat-value" id="countHigh">0</strong>
      </article>
      <article class="stat" style="--accent:#d48818">
        <span class="stat-label">Medium</span>
        <strong class="stat-value" id="countMedium">0</strong>
      </article>
      <article class="stat" style="--accent:#25805e">
        <span class="stat-label">Low</span>
        <strong class="stat-value" id="countLow">0</strong>
      </article>
    </section>

    <section class="lead-type-summary" aria-label="Статистика за типом ліда">
      <h2 class="summary-title">Статистика за lead_type</h2>
      <div class="type-stats" id="leadTypeStats"></div>
    </section>

    <section class="workspace">
      <div class="toolbar">
        <label class="search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7"></circle>
            <path d="m20 20-3.5-3.5"></path>
          </svg>
          <input id="search" type="search" placeholder="Пошук за назвою, містом, контактом…" autocomplete="off">
        </label>
        <div class="toolbar-actions">
          <label class="type-filter">
            <span>Lead type</span>
            <select id="leadTypeFilter" aria-label="Фільтр за типом ліда">
              <option value="ALL">Усі типи</option>
            </select>
          </label>
          <div class="filters" role="group" aria-label="Фільтр пріоритету">
            <button class="filter active" data-priority="ALL" type="button">Усі</button>
            <button class="filter" data-priority="HIGH" type="button">HIGH</button>
            <button class="filter" data-priority="MEDIUM" type="button">MEDIUM</button>
            <button class="filter" data-priority="LOW" type="button">LOW</button>
          </div>
          <button class="secondary" id="exportCsv" type="button">Експортувати CSV</button>
        </div>
      </div>
      <div class="table-meta">
        <span id="visibleCount">Показано: 0</span>
        <span>Натисніть заголовок колонки для сортування</span>
      </div>
      <div class="table-scroll">
        <table>
          <thead><tr id="headerRow"></tr></thead>
          <tbody id="tableBody"></tbody>
        </table>
        <div class="empty" id="emptyState" hidden>За цими умовами нічого не знайдено.</div>
      </div>
    </section>
    <p class="footer-note">Дані збережені всередині цього HTML-файлу.</p>
  </main>

  <script id="lead-data" type="application/json">__DATA__</script>
  <script>
    "use strict";

    const dataset = JSON.parse(document.getElementById("lead-data").textContent);
    const columns = dataset.columns;
    const leadTypes = dataset.leadTypes;
    const rows = dataset.rows.map((row, index) => ({ ...row, __index: index }));
    const priorityRank = { HIGH: 0, MEDIUM: 1, LOW: 2 };
    const labels = {
      name: "Компанія",
      country: "Країна",
      region: "Регіон",
      city: "Місто",
      address: "Адреса",
      phone: "Телефон",
      website: "Website",
      email: "Email",
      category: "Категорія",
      overture_id: "Overture ID",
      latitude: "Широта",
      longitude: "Довгота",
      source_release: "Реліз",
      score: "Score",
      priority: "Priority",
      score_reasons: "Причини оцінки",
      lead_type: "Тип ліда",
      recommended_offer: "Рекомендована пропозиція"
    };

    const state = {
      query: "",
      priority: "ALL",
      leadType: "ALL",
      sortColumn: "priority",
      sortDirection: "asc"
    };

    const body = document.getElementById("tableBody");
    const emptyState = document.getElementById("emptyState");
    const visibleCount = document.getElementById("visibleCount");
    const search = document.getElementById("search");
    const filterButtons = [...document.querySelectorAll(".filter")];
    const leadTypeFilter = document.getElementById("leadTypeFilter");

    function countPriority(priority) {
      return rows.filter(row => (row.priority || "").toUpperCase() === priority).length;
    }

    document.getElementById("countAll").textContent = rows.length;
    document.getElementById("countHigh").textContent = countPriority("HIGH");
    document.getElementById("countMedium").textContent = countPriority("MEDIUM");
    document.getElementById("countLow").textContent = countPriority("LOW");

    const leadTypeStats = document.getElementById("leadTypeStats");
    for (const leadType of leadTypes) {
      const count = rows.filter(row => row.lead_type === leadType).length;

      const card = document.createElement("article");
      card.className = "type-stat";
      const label = document.createElement("span");
      label.className = "type-stat-label";
      label.textContent = leadType;
      const value = document.createElement("strong");
      value.className = "type-stat-value";
      value.textContent = String(count);
      card.append(label, value);
      leadTypeStats.appendChild(card);

      const option = document.createElement("option");
      option.value = leadType;
      option.textContent = `${leadType} (${count})`;
      leadTypeFilter.appendChild(option);
    }

    function splitValues(value) {
      return String(value || "").split(/[,;\n]+/).map(item => item.trim()).filter(Boolean);
    }

    function truncate(value, maxLength = 34) {
      if (value.length <= maxLength) return value;
      return value.slice(0, maxLength - 1) + "…";
    }

    function safeExternalUrl(value) {
      const text = String(value || "").trim();
      if (/^https?:\/\//i.test(text)) return text;
      return "https://" + text;
    }

    function makeLink(href, text, title) {
      const link = document.createElement("a");
      link.href = href;
      link.textContent = text;
      link.title = title;
      return link;
    }

    function renderContactLinks(cell, value, type) {
      const values = splitValues(value);
      if (!values.length) {
        cell.textContent = "—";
        cell.classList.add("muted");
        return;
      }

      const list = document.createElement("div");
      list.className = "link-list";
      for (const item of values) {
        if (type === "website") {
          list.appendChild(makeLink(safeExternalUrl(item), truncate(item), item));
        } else if (type === "email") {
          list.appendChild(makeLink("mailto:" + item, item, item));
        } else {
          list.appendChild(makeLink("tel:" + item.replace(/\s+/g, ""), item, item));
        }
      }
      cell.appendChild(list);
    }

    function makeCell(column, value) {
      const cell = document.createElement("td");
      const text = String(value ?? "");

      if (column === "website" || column === "email" || column === "phone") {
        renderContactLinks(cell, text, column);
      } else if (column === "priority") {
        const priority = text.toUpperCase() || "LOW";
        const badge = document.createElement("span");
        badge.className = "badge badge-" + priority.toLowerCase();
        badge.textContent = priority;
        cell.appendChild(badge);
      } else if (column === "score") {
        const score = Number(text || 0);
        const level = score >= 5 ? "high" : score >= 2 ? "medium" : "low";
        const badge = document.createElement("span");
        badge.className = "score score-" + level;
        badge.textContent = String(score);
        cell.appendChild(badge);
      } else if (column === "lead_type") {
        const badge = document.createElement("span");
        badge.className = "type-badge";
        badge.textContent = text || "UNKNOWN";
        cell.appendChild(badge);
      } else {
        cell.textContent = text || "—";
        if (!text) cell.classList.add("muted");
      }

      if (column === "name") cell.classList.add("company");
      if (["address", "category", "score_reasons", "recommended_offer"].includes(column)) {
        cell.classList.add("wrap");
      }
      if (["latitude", "longitude", "source_release"].includes(column)) cell.classList.add("nowrap");
      return cell;
    }

    function normalizedValue(row, column) {
      const value = row[column] ?? "";
      if (column === "priority") return priorityRank[String(value).toUpperCase()] ?? 99;
      if (["score", "latitude", "longitude"].includes(column)) {
        const number = Number(value);
        return Number.isFinite(number) ? number : Number.NEGATIVE_INFINITY;
      }
      return String(value).toLocaleLowerCase("uk");
    }

    function compareRows(a, b) {
      const left = normalizedValue(a, state.sortColumn);
      const right = normalizedValue(b, state.sortColumn);
      let result;
      if (typeof left === "number" && typeof right === "number") {
        result = left - right;
      } else {
        result = String(left).localeCompare(String(right), "uk", { numeric: true });
      }
      if (result === 0) result = a.__index - b.__index;
      return state.sortDirection === "asc" ? result : -result;
    }

    function filteredRows() {
      const query = state.query.toLocaleLowerCase("uk");
      return rows
        .filter(row => state.priority === "ALL" || String(row.priority).toUpperCase() === state.priority)
        .filter(row => state.leadType === "ALL" || row.lead_type === state.leadType)
        .filter(row => !query || columns.some(column =>
          String(row[column] ?? "").toLocaleLowerCase("uk").includes(query)
        ))
        .sort(compareRows);
    }

    function renderHeader() {
      const header = document.getElementById("headerRow");
      header.replaceChildren();
      for (const column of columns) {
        const th = document.createElement("th");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "sort-button";
        button.dataset.column = column;

        const title = document.createElement("span");
        title.textContent = labels[column] || column.replaceAll("_", " ");
        button.appendChild(title);

        if (state.sortColumn === column) {
          const mark = document.createElement("span");
          mark.className = "sort-mark";
          mark.textContent = state.sortDirection === "asc" ? "▲" : "▼";
          button.appendChild(mark);
        }

        button.addEventListener("click", () => {
          if (state.sortColumn === column) {
            state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
          } else {
            state.sortColumn = column;
            state.sortDirection = column === "score" ? "desc" : "asc";
          }
          render();
        });
        th.appendChild(button);
        header.appendChild(th);
      }
    }

    function render() {
      const visible = filteredRows();
      renderHeader();
      body.replaceChildren();

      for (const row of visible) {
        const tr = document.createElement("tr");
        for (const column of columns) tr.appendChild(makeCell(column, row[column]));
        body.appendChild(tr);
      }

      visibleCount.textContent = `Показано: ${visible.length} із ${rows.length}`;
      emptyState.hidden = visible.length !== 0;
      document.querySelector("table").hidden = visible.length === 0;
    }

    function setPriority(priority) {
      state.priority = priority;
      for (const button of filterButtons) {
        button.classList.toggle("active", button.dataset.priority === priority);
      }
      render();
    }

    search.addEventListener("input", event => {
      state.query = event.target.value.trim();
      render();
    });

    for (const button of filterButtons) {
      button.addEventListener("click", () => setPriority(button.dataset.priority));
    }

    leadTypeFilter.addEventListener("change", event => {
      state.leadType = event.target.value;
      render();
    });

    document.getElementById("highOnly").addEventListener("click", () => setPriority("HIGH"));

    function csvEscape(value) {
      const text = String(value ?? "");
      return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
    }

    document.getElementById("exportCsv").addEventListener("click", () => {
      const visible = filteredRows();
      const lines = [
        columns.map(csvEscape).join(","),
        ...visible.map(row => columns.map(column => csvEscape(row[column])).join(","))
      ];
      const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "filtered_leads.csv";
      link.click();
      URL.revokeObjectURL(url);
    });

    render();
  </script>
</body>
</html>
"""


def read_csv(input_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header.")
        columns = list(reader.fieldnames)
        rows = [
            {column: row.get(column, "") or "" for column in columns} for row in reader
        ]
    return columns, rows


def build_html(columns: list[str], rows: list[dict[str, str]]) -> str:
    payload = json.dumps(
        {"columns": columns, "leadTypes": LEAD_TYPES, "rows": rows},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", r"<\/")
    return HTML_TEMPLATE.replace("__DATA__", payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a standalone offline HTML viewer for scored leads."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output files must be different.")
        columns, rows = read_csv(args.input)
        html = build_html(columns, rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html, encoding="utf-8")
        print(f"Створено: {args.output}")
        print(f"Компаній: {len(rows)}")
        lead_type_counts = Counter(row.get("lead_type", "UNKNOWN") for row in rows)
        print("Статистика за lead_type:")
        for lead_type in LEAD_TYPES:
            print(f"  {lead_type}: {lead_type_counts[lead_type]}")
        return 0
    except (OSError, ValueError, csv.Error) as error:
        print(f"Помилка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
