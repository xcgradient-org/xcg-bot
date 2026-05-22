from __future__ import annotations

import base64
import json
import logging
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.domain.dates import MADRID_TZ, week_context_for_date
from backend.domain.prompts import (
    WEEK_PWP_COMPOSE_PROMPT,
    WEEK_PWP_COMPLETED_ANALYSIS_PROMPT,
    WEEK_PWP_PENDING_ANALYSIS_PROMPT,
)
from backend.domain.text import finalize_sentence


LOGGER = logging.getLogger("xcg_bot.week_pwp")
DEFAULT_WPWP_NAME = "week-report"
FALLBACK_LOGO = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2rN5kA"
    "AAAASUVORK5CYII="
)
GROUPS_PER_PAGE = 2
DEFAULT_BLANK_PAGES = 2
_TASK_STATUS_PREFIX_RE = re.compile(
    r"^[⚠↩✅]\s*(?:stale|carryover|carry[\s\-]over|done)\s*\|\s*",
    re.IGNORECASE,
)

MAKEFILE_TEXT = """DOC ?= $(notdir $(CURDIR))

.PHONY: deps build pdf clean

deps:
\tnpm install --no-audit --no-fund

build: deps
\tnode build.js

pdf: build
\t./update.sh

clean:
\trm -rf output
"""

BUILD_JS_TEXT = """const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const theme = require("./shared/theme");
const { createHelpers } = require("./shared/helpers");
const deck = require("./deck");

async function main() {
  const outputDir = path.join(__dirname, "output");
  fs.mkdirSync(path.join(outputDir, "slides"), { recursive: true });

  const pres = new pptxgen();
  pres.layout = theme.layout;
  pres.title = deck.title || deck.id || "Untitled";
  pres.author = deck.author || "xcg-week-pwp";

  const helpers = createHelpers(pres, theme);
  await deck.build(pres, {
    theme,
    assetsDir: path.join(__dirname, "assets"),
    outputDir,
    ...helpers,
  });

  const outFile = path.join(outputDir, `${deck.id || "presentation"}.pptx`);
  await pres.writeFile({ fileName: outFile });
  console.log(`✅ ${path.relative(process.cwd(), outFile)} written`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""

THEME_JS_TEXT = """module.exports = {
  layout: "LAYOUT_16x9",
  width: 10,
  height: 5.625,
  fonts: {
    heading: "Bebas Neue",
    body: "Poppins",
    quote: "Merriweather",
  },
  colors: {
    red: "CC2222",
    black: "1A1A1A",
    white: "FFFFFF",
    gray: "555555",
    lightGray: "E8E8E8",
    offWhite: "F7F7F7",
    redDark: "991A1A",
    redLight: "EE4444",
  },
};
"""

HELPERS_JS_TEXT = """function createHelpers(pres, theme) {
  const C = theme.colors;
  const W = theme.width;
  const H = theme.height;

  function sectionDivider(title, num, darkBg = false) {
    const s = pres.addSlide();
    s.background = { color: darkBg ? C.black : C.red };
    s.addText(String(num).padStart(2, "0"), {
      x: 5.5,
      y: -0.3,
      w: 4.5,
      h: H + 0.5,
      fontFace: theme.fonts.heading,
      fontSize: 220,
      color: darkBg ? "2A2A2A" : "BB1111",
      bold: true,
      align: "right",
      valign: "middle",
      margin: 0,
    });
    s.addText(title, {
      x: 0.7,
      y: 1.8,
      w: 7,
      h: 2,
      fontFace: theme.fonts.heading,
      fontSize: 64,
      color: C.white,
      bold: true,
      align: "left",
      valign: "middle",
      margin: 0,
    });
    return s;
  }

  function contentSlide(bg = C.white) {
    const s = pres.addSlide();
    s.background = { color: bg };
    return s;
  }

  function slideTitle(slide, text, y = 0.38) {
    slide.addText(text, {
      x: 0.6,
      y,
      w: 8.8,
      h: 0.52,
      fontFace: theme.fonts.heading,
      fontSize: 24,
      color: C.black,
      bold: true,
      align: "left",
      margin: 0,
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6,
      y: y + 0.57,
      w: 1.2,
      h: 0.055,
      fill: { color: C.red },
      line: { color: C.red },
    });
  }

  function statBox(slide, number, label, x, y, w = 2.8, h = 1.5) {
    slide.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w,
      h,
      fill: { color: C.offWhite },
      line: { color: C.lightGray, width: 1 },
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 0.08,
      h,
      fill: { color: C.red },
      line: { color: C.red },
    });
    slide.addText(number, {
      x: x + 0.18,
      y: y + 0.15,
      w: w - 0.25,
      h: 0.9,
      fontFace: theme.fonts.heading,
      fontSize: 34,
      color: C.red,
      bold: true,
      align: "left",
      margin: 0,
    });
    slide.addText(label, {
      x: x + 0.18,
      y: y + 0.98,
      w: w - 0.25,
      h: 0.38,
      fontFace: theme.fonts.body,
      fontSize: 11,
      color: C.gray,
      align: "left",
      margin: 0,
    });
  }

  return {
    C,
    W,
    H,
    sectionDivider,
    contentSlide,
    slideTitle,
    statBox,
  };
}

module.exports = {
  createHelpers,
};
"""

UPDATE_SH_TEXT = """#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="{{NAME}}"
OUTPUT_DIR="$DIR/output"
PPTX_FILE="$OUTPUT_DIR/$NAME.pptx"
PDF_FILE="$OUTPUT_DIR/$NAME.pdf"
SLIDES_DIR="$OUTPUT_DIR/slides"
PROFILE_DIR="$OUTPUT_DIR/.lo-profile"

mkdir -p "$OUTPUT_DIR" "$SLIDES_DIR" "$PROFILE_DIR"

cd "$DIR" && node build.js

if ! command -v soffice >/dev/null 2>&1; then
  echo "Missing dependency: soffice (LibreOffice) — skipping PDF/slides export"
  exit 0
fi

if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "Missing dependency: pdftoppm (poppler-utils) — skipping slides export"
  exit 0
fi

rm -f "$PDF_FILE"
soffice --headless -env:UserInstallation="file://$PROFILE_DIR" --convert-to pdf --outdir "$OUTPUT_DIR" "$PPTX_FILE"

rm -f "$SLIDES_DIR"/slide-*.jpg
pdftoppm -jpeg -r 150 "$PDF_FILE" "$SLIDES_DIR/slide"

echo "✅ $PPTX_FILE"
echo "✅ $PDF_FILE"
echo "✅ $SLIDES_DIR"
"""

README_TEXT = """# {title}

Created {today} with `flux pwp week-report --week {week_number} --person {person_query}`.

LLM runbook — exact commands (copy/paste friendly):

Prerequisites:
- node and npm
- Optional: LibreOffice and poppler-utils for PDF + slide image export
- Network access for npm packages

Commands (run in project root):

```bash
# Install Node dependencies (first time)
make deps

# Build PPTX (generates output/{slug}.pptx)
make build

# Export PDF + slide images (requires LibreOffice + poppler)
make pdf

# Clean generated artifacts
make clean
```

Project layout

| File | Purpose |
|------|---------|
| `Makefile` | Build helpers: `make deps`, `make build`, `make pdf`, `make clean` |
| `package.json` | Node project configuration |
| `data.js` | Generated weekly report data and slide plan |
| `deck.js` | Build function — renders the weekly report deck |
| `shared/theme.js` | Brand colors and fonts |
| `shared/helpers.js` | Slide helper functions |
| `assets/` | Images referenced in `deck.js` via `assetsDir` |
| `output/` | Generated PPTX, PDF, and slide JPGs (git-ignored) |

Notes

- `flux pwp week-report --week {week_number} --person {person_query}` is the generator command used to create this project (calls the xcg-bot internal API).
- `make build` and `make pdf` work without editing the project files.
- `update.sh` exports a PDF and slide images when LibreOffice and poppler are available.
"""

DECK_JS_TEXT = """const data = require("./data");

function addWrappedText(slide, text, options) {
  slide.addText(text || "", {
    fontFace: options.fontFace,
    fontSize: options.fontSize,
    color: options.color,
    x: options.x,
    y: options.y,
    w: options.w,
    h: options.h,
    margin: options.margin ?? 0,
    breakLine: false,
    fit: "shrink",
    valign: options.valign || "top",
    bold: options.bold || false,
  });
}

function drawBars(slide, chart, theme, rect, x, y, w, h) {
  if (!chart || !Array.isArray(chart.labels) || !Array.isArray(chart.values) || !chart.labels.length) {
    return;
  }

  const maxValue = Math.max(...chart.values.map((value) => Number(value) || 0), 1);
  const rowHeight = h / chart.labels.length;
  const labelWidth = Math.min(1.9, w * 0.35);
  const barLeft = x + labelWidth + 0.08;
  const barWidth = w - labelWidth - 0.08;

  slide.addText(chart.title || "Theme balance", {
    x,
    y: y - 0.28,
    w,
    h: 0.22,
    fontFace: theme.fonts.body,
    fontSize: 9,
    color: theme.colors.gray,
    bold: true,
    margin: 0,
  });

  chart.labels.forEach((label, index) => {
    const value = Number(chart.values[index]) || 0;
    const rowY = y + index * rowHeight;
    const barH = Math.max(0.12, rowHeight * 0.42);
    const barY = rowY + (rowHeight - barH) / 2;
    const barW = Math.max(0.06, (value / maxValue) * barWidth);

    addWrappedText(slide, label, {
      x,
      y: rowY + 0.02,
      w: labelWidth,
      h: rowHeight,
      fontFace: theme.fonts.body,
      fontSize: 10,
      color: theme.colors.black,
      margin: 0,
      valign: "mid",
    });

    slide.addShape(rect, {
      x: barLeft,
      y: barY,
      w: barWidth,
      h: barH,
      fill: { color: theme.colors.lightGray },
      line: { color: theme.colors.lightGray },
    });
    slide.addShape(rect, {
      x: barLeft,
      y: barY,
      w: barW,
      h: barH,
      fill: { color: theme.colors.red },
      line: { color: theme.colors.red },
    });
    slide.addText(String(value), {
      x: barLeft + barW + 0.05,
      y: barY - 0.02,
      w: 0.4,
      h: barH + 0.04,
      fontFace: theme.fonts.body,
      fontSize: 9,
      color: theme.colors.gray,
      bold: true,
      margin: 0,
    });
  });
}

function renderBullets(slide, bullets, theme, x, y, w, h) {
  const items = Array.isArray(bullets) ? bullets.filter(Boolean) : [];
  if (!items.length) {
    return;
  }
  const lineHeight = Math.max(0.35, h / items.length);
  items.slice(0, 8).forEach((bullet, index) => {
    slide.addText(`• ${bullet}`, {
      x,
      y: y + index * lineHeight,
      w,
      h: lineHeight,
      fontFace: theme.fonts.body,
      fontSize: 11,
      color: theme.colors.black,
      margin: 0,
      fit: "shrink",
    });
  });
}

function renderGroupCard(slide, group, theme, rect, x, y, w, h) {
  slide.addShape(rect, {
    x,
    y,
    w,
    h,
    fill: { color: theme.colors.offWhite },
    line: { color: theme.colors.lightGray, width: 1 },
  });
  slide.addShape(rect, {
    x,
    y,
    w: 0.08,
    h,
    fill: { color: theme.colors.red },
    line: { color: theme.colors.red },
  });
  slide.addText(group.title || "Untitled group", {
    x: x + 0.16,
    y: y + 0.1,
    w: w - 0.22,
    h: 0.28,
    fontFace: theme.fonts.heading,
    fontSize: 18,
    color: theme.colors.black,
    bold: true,
    margin: 0,
    fit: "shrink",
  });
  slide.addText(group.summary || "", {
    x: x + 0.16,
    y: y + 0.42,
    w: w - 0.22,
    h: 0.38,
    fontFace: theme.fonts.body,
    fontSize: 10,
    color: theme.colors.gray,
    margin: 0,
    fit: "shrink",
  });
  const taskY = y + 0.84;
  const tasks = Array.isArray(group.tasks) ? group.tasks.filter(Boolean) : [];
  const taskLineHeight = tasks.length ? Math.min(0.25, Math.max(0.18, (h - 0.98) / Math.max(tasks.length, 1))) : 0.2;
  tasks.slice(0, 5).forEach((task, index) => {
    slide.addText(`• ${task}`, {
      x: x + 0.16,
      y: taskY + index * taskLineHeight,
      w: w - 0.22,
      h: taskLineHeight,
      fontFace: theme.fonts.body,
      fontSize: 9.5,
      color: theme.colors.black,
      margin: 0,
      fit: "shrink",
    });
  });
  if (tasks.length > 5) {
    slide.addText(`… +${tasks.length - 5} more`, {
      x: x + 0.16,
      y: taskY + 5 * taskLineHeight,
      w: w - 0.22,
      h: taskLineHeight,
      fontFace: theme.fonts.body,
      fontSize: 9,
      color: theme.colors.gray,
      italic: true,
      margin: 0,
    });
  }
  const taskAreaBottom = taskY + Math.min(tasks.length, 5) * taskLineHeight;
  if (group.detail && taskAreaBottom + 0.04 < y + h - 0.28) {
    slide.addText(group.detail, {
      x: x + 0.16,
      y: y + h - 0.28,
      w: w - 0.22,
      h: 0.22,
      fontFace: theme.fonts.body,
      fontSize: 8.5,
      color: theme.colors.gray,
      italic: true,
      margin: 0,
      fit: "shrink",
    });
  }
}

function renderSectionPage(slide, page, theme, rect) {
  slide.addText(page.headline || page.title || "Section", {
    x: 0.6,
    y: 0.35,
    w: 8.8,
    h: 0.42,
    fontFace: theme.fonts.heading,
    fontSize: 28,
    color: theme.colors.black,
    bold: true,
    margin: 0,
  });
  slide.addShape(rect, {
    x: 0.6,
    y: 0.92,
    w: 1.2,
    h: 0.05,
    fill: { color: theme.colors.red },
    line: { color: theme.colors.red },
  });
  addWrappedText(slide, page.summary || "", {
    x: 0.6,
    y: 1.07,
    w: 8.7,
    h: 0.5,
    fontFace: theme.fonts.body,
    fontSize: 12,
    color: theme.colors.gray,
    margin: 0,
  });

  const leftX = 0.6;
  const rightX = 6.35;
  const contentY = 1.7;
  const contentH = 3.45;
  const groups = Array.isArray(page.groups) ? page.groups : [];
  if (groups.length === 0) {
    renderGroupCard(slide, { title: "No tasks", summary: "There were no matching tasks for this section.", tasks: [] }, theme, rect, leftX, contentY, 8.7, 1.1);
  } else if (groups.length === 1) {
    renderGroupCard(slide, groups[0], theme, rect, leftX, contentY, 5.5, 2.0);
  } else {
    const hasChart = page.chart && Array.isArray(page.chart.labels) && page.chart.labels.length > 0;
    if (hasChart) {
      const cardW = 5.5;
      const cardH = 1.45;
      groups.slice(0, 4).forEach((group, index) => {
        renderGroupCard(slide, group, theme, rect, leftX, contentY + index * (cardH + 0.2), cardW, cardH);
      });
    } else {
      const columnWidth = 5.1;
      const boxHeight = 1.58;
      groups.slice(0, 4).forEach((group, index) => {
        const col = index % 2;
        const row = Math.floor(index / 2);
        renderGroupCard(slide, group, theme, rect, leftX + col * (columnWidth + 0.18), contentY + row * (boxHeight + 0.2), columnWidth, boxHeight);
      });
    }
  }

  if (page.chart) {
    drawBars(slide, page.chart, theme, rect, rightX, contentY, 3.1, 2.2);
  }

  if (page.chart && Array.isArray(page.highlights) && page.highlights.length) {
    renderBullets(slide, page.highlights, theme, rightX, 3.95, 3.05, 1.0);
  }
}

function renderCoverPage(slide, page, theme, rect) {
  slide.addText(page.headline || "Week report", {
    x: 0.65,
    y: 0.45,
    w: 5.5,
    h: 0.72,
    fontFace: theme.fonts.heading,
    fontSize: 36,
    color: theme.colors.black,
    bold: true,
    margin: 0,
    fit: "shrink",
  });
  slide.addText(page.subtitle || "", {
    x: 0.65,
    y: 1.1,
    w: 7.0,
    h: 0.3,
    fontFace: theme.fonts.body,
    fontSize: 14,
    color: theme.colors.gray,
    bold: true,
    margin: 0,
  });
  slide.addShape(rect, {
    x: 0.65,
    y: 1.45,
    w: 1.6,
    h: 0.06,
    fill: { color: theme.colors.red },
    line: { color: theme.colors.red },
  });
  addWrappedText(slide, page.summary || "", {
    x: 0.65,
    y: 1.65,
    w: 5.6,
    h: 1.15,
    fontFace: theme.fonts.body,
    fontSize: 14,
    color: theme.colors.black,
    margin: 0,
  });
  addWrappedText(slide, page.intro || "", {
    x: 0.65,
    y: 2.78,
    w: 5.6,
    h: 0.8,
    fontFace: theme.fonts.body,
    fontSize: 10.5,
    color: theme.colors.gray,
    margin: 0,
  });

  const stats = Array.isArray(page.stats) ? page.stats : [];
  stats.slice(0, 3).forEach((stat, index) => {
    slide.addShape(rect, {
      x: 6.4 + index * 1.1,
      y: 0.55,
      w: 0.9,
      h: 0.45,
      fill: { color: theme.colors.offWhite },
      line: { color: theme.colors.lightGray },
    });
    slide.addText(String(stat.number ?? ""), {
      x: 6.46 + index * 1.1,
      y: 0.62,
      w: 0.78,
      h: 0.2,
      fontFace: theme.fonts.heading,
      fontSize: 18,
      color: theme.colors.red,
      bold: true,
      align: "center",
      margin: 0,
    });
    slide.addText(String(stat.label ?? ""), {
      x: 6.42 + index * 1.1,
      y: 0.82,
      w: 0.86,
      h: 0.12,
      fontFace: theme.fonts.body,
      fontSize: 6.5,
      color: theme.colors.gray,
      align: "center",
      margin: 0,
    });
  });

  if (page.chart) {
    drawBars(slide, page.chart, theme, rect, 6.35, 1.35, 2.95, 2.2);
  }

  slide.addShape(rect, {
    x: 0.65,
    y: 4.55,
    w: 8.7,
    h: 0.45,
    fill: { color: theme.colors.offWhite },
    line: { color: theme.colors.lightGray },
  });
  slide.addText(page.footer || "Generated weekly report", {
    x: 0.8,
    y: 4.67,
    w: 8.4,
    h: 0.16,
    fontFace: theme.fonts.body,
    fontSize: 8.5,
    color: theme.colors.gray,
    margin: 0,
  });
}

function renderNextWeekPage(slide, page, theme, rect) {
  slide.addText(page.headline || "Next week", {
    x: 0.6,
    y: 0.35,
    w: 8.8,
    h: 0.42,
    fontFace: theme.fonts.heading,
    fontSize: 28,
    color: theme.colors.black,
    bold: true,
    margin: 0,
  });
  slide.addShape(rect, {
    x: 0.6,
    y: 0.92,
    w: 1.2,
    h: 0.05,
    fill: { color: theme.colors.red },
    line: { color: theme.colors.red },
  });
  addWrappedText(slide, page.summary || "", {
    x: 0.6,
    y: 1.05,
    w: 8.7,
    h: 0.5,
    fontFace: theme.fonts.body,
    fontSize: 12,
    color: theme.colors.gray,
    margin: 0,
  });
  renderBullets(slide, page.bullets || [], theme, 0.72, 1.72, 8.2, 2.0);
  slide.addText("The following slides are intentionally left blank for manual additions.", {
    x: 0.72,
    y: 4.88,
    w: 8.2,
    h: 0.18,
    fontFace: theme.fonts.body,
    fontSize: 8.5,
    color: theme.colors.gray,
    italic: true,
    margin: 0,
  });
}

function renderBlankPage(slide) {
  slide.background = { color: "FFFFFF" };
}

module.exports = {
  id: data.id,
  title: data.title,
  build(pres, { theme, contentSlide, slideTitle, sectionDivider }) {
    const rect = pres.shapes.RECTANGLE;
    for (const page of data.pages || []) {
      if (page.kind === "divider") {
        sectionDivider(page.title || "Section", page.number || "01", Boolean(page.darkBg));
        continue;
      }

      if (page.kind === "blank") {
        const slide = contentSlide(theme.colors.white);
        renderBlankPage(slide);
        continue;
      }

      const slide = contentSlide(page.bg || theme.colors.white);
      if (page.kind === "cover") {
        renderCoverPage(slide, page, theme, rect);
        continue;
      }
      if (page.kind === "next_week") {
        renderNextWeekPage(slide, page, theme, rect);
        continue;
      }

      renderSectionPage(slide, page, theme, rect);
    }
  },
};
"""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return slug.strip("-")


def _clean_task_line(text: str) -> str:
    text = _TASK_STATUS_PREFIX_RE.sub("", str(text or "")).strip()
    return finalize_sentence(text)


def _task_list_text(descriptions: list[str]) -> str:
    return "\n".join(f"- {description}" for description in descriptions) or "- none"


def _current_week_code() -> str:
    _year, _week, week_code, _quarter = week_context_for_date(datetime.now(MADRID_TZ).isoformat())
    return week_code


def _resolve_week_code(week_number: int) -> str:
    if week_number == 0:
        return _current_week_code()
    current_code = _current_week_code()
    year_part = current_code.split("-W", 1)[0]
    return f"{year_part}-W{week_number:02d}"


def _merge_buckets(descriptions: list[str], *, max_groups: int = 4) -> list[dict[str, Any]]:
    buckets: dict[str, list[str]] = {}
    for description in descriptions:
        cleaned = _clean_task_line(description)
        if not cleaned:
            continue
        stripped = re.sub(
            r"^(?:fix|build|create|implement|update|improve|refine|design|prepare|review|ship|add|remove|draft|plan|organize|analyse|analyze)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        words = re.findall(r"[A-Za-z0-9]+", stripped)
        key = " ".join(words[:2]).strip().title() if words else "General"
        buckets.setdefault(key or "General", []).append(cleaned)

    if not buckets:
        return [{"title": "General", "summary": "No matching tasks were available.", "tasks": [], "detail": ""}]

    items = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    grouped: list[dict[str, Any]] = []
    overflow: list[str] = []
    for index, (title, tasks) in enumerate(items):
        if index < max_groups - 1:
            grouped.append(
                {
                    "title": title,
                    "summary": f"{len(tasks)} task(s) grouped around {title.lower()}.",
                    "tasks": tasks,
                    "detail": "",
                }
            )
        else:
            overflow.extend(tasks)
    if overflow:
        grouped.append(
            {
                "title": "Other work",
                "summary": f"{len(overflow)} task(s) that did not fit a dominant theme.",
                "tasks": overflow,
                "detail": "",
            }
        )
    return grouped


def _coerce_list_of_strings(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _clean_task_line(str(item))
        if text:
            items.append(text)
        if limit is not None and len(items) >= limit:
            break
    return items


def _coerce_groups(payload: dict[str, Any] | None, fallback_descriptions: list[str], *, detail_key: str) -> list[dict[str, Any]]:
    if not payload:
        return _merge_buckets(fallback_descriptions)

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        return _merge_buckets(fallback_descriptions)

    groups: list[dict[str, Any]] = []
    for group in raw_groups:
        if not isinstance(group, dict):
            continue
        title = _clean_task_line(group.get("title", "")) or "General"
        summary = _clean_task_line(group.get("summary", ""))
        tasks = _coerce_list_of_strings(group.get("tasks"), limit=6) or []
        detail = _clean_task_line(group.get(detail_key, group.get("impact", group.get("risk", ""))))
        if not tasks and not summary:
            continue
        groups.append(
            {
                "title": title,
                "summary": summary or f"{len(tasks)} task(s) in this theme.",
                "tasks": tasks,
                "detail": detail,
            }
        )
    return groups or _merge_buckets(fallback_descriptions)


def _coerce_chart(payload: dict[str, Any] | None, groups: list[dict[str, Any]], section_title: str) -> dict[str, Any]:
    labels = [group["title"] for group in groups]
    values = [len(group.get("tasks", [])) for group in groups]
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if isinstance(chart, dict):
        chart_labels = _coerce_list_of_strings(chart.get("labels"))
        if chart_labels:
            labels = chart_labels
    return {
        "title": str(chart.get("title") if isinstance(chart, dict) and chart.get("title") else f"{section_title} balance"),
        "labels": labels,
        "values": values,
        "note": str(chart.get("note") if isinstance(chart, dict) and chart.get("note") else ""),
    }


def _split_groups(groups: list[dict[str, Any]], size: int = GROUPS_PER_PAGE) -> list[list[dict[str, Any]]]:
    return [groups[index : index + size] for index in range(0, len(groups), size)] or [[]]


def _embedded_logo_bytes() -> bytes:
    return FALLBACK_LOGO


@dataclass(slots=True)
class WeekPwpBuildResult:
    project_dir: Path
    week_code: str
    role: str
    founder_name: str
    task_count: int
    done_count: int
    pending_count: int


class WeekPwpReportService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def generate_project(
        self,
        *,
        week_number: int,
        person: str,
        out_dir: Path | None = None,
    ) -> WeekPwpBuildResult:
        member_query = str(person or "").strip()
        if not member_query:
            raise ValueError("person must be a non-empty name, email, or role.")

        if not 0 <= week_number <= 52:
            raise ValueError("Week must be between 0 and 52.")

        try:
            member = self.runtime.notion.find_team_member(member_query)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if not member:
            raise RuntimeError(f"No active team member found matching {member_query!r}.")

        task_role = (member.get("role") or "").strip() or member.get("name", "").strip()
        if not task_role:
            raise RuntimeError("Resolved team member has no role or name for task matching.")

        normalized_role = task_role
        founder_name = member["name"]

        week_code = _resolve_week_code(week_number)
        all_tasks, done_tasks, pending_tasks = self.runtime.notion.query_week_tasks(
            normalized_role,
            week_code,
            founder_name=founder_name,
        )

        done_descriptions = self.runtime.notion.task_descriptions(done_tasks)
        pending_descriptions = self.runtime.notion.task_descriptions(pending_tasks)

        done_analysis = self._analyze_done(week_code, normalized_role, founder_name, done_descriptions)
        pending_analysis = self._analyze_pending(week_code, normalized_role, founder_name, pending_descriptions)
        composition = self._compose_copy(week_code, normalized_role, founder_name, done_analysis, pending_analysis)
        resolved_week_number = week_number or int(week_code.split("-W", 1)[1])

        plan = self._assemble_plan(
            week_number=resolved_week_number,
            week_code=week_code,
            role=normalized_role,
            founder_name=founder_name,
            person_query=member_query,
            all_tasks=all_tasks,
            done_count=len(done_descriptions),
            pending_count=len(pending_descriptions),
            done_analysis=done_analysis,
            pending_analysis=pending_analysis,
            composition=composition,
        )

        base_dir = (out_dir or Path.cwd()).resolve()
        project_slug = plan["id"]
        project_dir = base_dir / project_slug
        if project_dir.exists():
            raise FileExistsError(f"Directory already exists: {project_dir}")
        self._write_project(project_dir, plan)
        return WeekPwpBuildResult(
            project_dir=project_dir,
            week_code=week_code,
            role=normalized_role,
            founder_name=founder_name,
            task_count=len(all_tasks),
            done_count=len(done_tasks),
            pending_count=len(pending_tasks),
        )

    def get_raw_tasks(self, *, week_number: int, person: str) -> dict:
        """Return raw task lists for a person/week — no LLM, no ZIP."""
        member_query = str(person or "").strip()
        if not member_query:
            raise ValueError("person must be a non-empty name.")
        if not 1 <= week_number <= 53:
            raise ValueError("Week must be between 1 and 53.")
        try:
            member = self.runtime.notion.find_team_member(member_query)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if not member:
            raise RuntimeError(f"No active team member found matching {member_query!r}.")
        role = (member.get("role") or "").strip() or member["name"].strip()
        founder_name = member["name"]
        week_code = _resolve_week_code(week_number)
        all_tasks, done_tasks, pending_tasks = self.runtime.notion.query_week_tasks(
            role, week_code, founder_name=founder_name
        )
        done_descriptions = self.runtime.notion.task_descriptions(done_tasks)
        pending_descriptions = self.runtime.notion.task_descriptions(pending_tasks)
        return {
            "person": founder_name,
            "week_code": week_code,
            "role": role,
            "counts": {"total": len(all_tasks), "done": len(done_tasks), "pending": len(pending_tasks)},
            "done": done_descriptions,
            "pending": pending_descriptions,
        }

    def scaffold_project_zip(self, *, week_number: int, person: str) -> tuple[bytes, str]:
        """Return a project ZIP with structure but placeholder data.js (no LLM)."""
        member_query = str(person or "").strip()
        if not member_query:
            raise ValueError("person must be a non-empty name.")
        try:
            member = self.runtime.notion.find_team_member(member_query)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if not member:
            raise RuntimeError(f"No active team member found matching {member_query!r}.")
        role = (member.get("role") or "").strip() or member["name"].strip()
        founder_name = member["name"]
        week_code = _resolve_week_code(week_number)
        project_slug = _slugify(f"week-{week_number:02d}-{founder_name}-{role}-report")
        plan = {
            "id": project_slug,
            "title": f"Week {week_number} report",
            "subtitle": f"{role} · {founder_name}",
            "week_code": week_code,
            "role": role,
            "founder_name": founder_name,
            "person_query": person,
            "counts": {"total": 0, "done": 0, "pending": 0},
            "pages": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            project_dir = base / project_slug
            self._write_project(project_dir, plan)
            archive_path = shutil.make_archive(
                str(base / "bundle"), "zip",
                root_dir=str(project_dir.parent), base_dir=project_slug,
            )
            data = Path(archive_path).read_bytes()
            return data, f"{project_slug}.zip"

    def build_project_zip(
        self,
        *,
        week_number: int,
        person: str,
    ) -> tuple[bytes, str]:
        """Build the deck project in a temporary directory and return (zip bytes, filename)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            result = self.generate_project(week_number=week_number, person=person, out_dir=base)
            slug = result.project_dir.name
            archive_path = shutil.make_archive(
                str(base / "bundle"),
                "zip",
                root_dir=str(result.project_dir.parent),
                base_dir=slug,
            )
            data = Path(archive_path).read_bytes()
            Path(archive_path).unlink(missing_ok=True)
            shutil.rmtree(result.project_dir, ignore_errors=True)
            return data, f"{slug}.zip"

    def _analyze_done(
        self,
        week_code: str,
        role: str,
        founder_name: str,
        done_descriptions: list[str],
    ) -> dict[str, Any]:
        fallback_groups = _merge_buckets(done_descriptions)
        fallback_chart = _coerce_chart({}, fallback_groups, "Completed work")
        payload = None
        if done_descriptions:
            try:
                payload = self.runtime.reflection.generate_json_response(
                    system_prompt=WEEK_PWP_COMPLETED_ANALYSIS_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "week_code": week_code,
                            "role": role,
                            "founder_name": founder_name,
                            "completed_tasks": done_descriptions,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    max_output_tokens=2500,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Completed-work synthesis failed; falling back to heuristics: %s", exc)

        if not payload:
            return {
                "summary": f"{len(done_descriptions)} completed task(s) were grouped for {role}.",
                "headline": "Completed work",
                "chart": fallback_chart,
                "groups": fallback_groups,
                "insights": [
                    f"{len(done_descriptions)} completed task(s) captured for {founder_name}.",
                ],
            }

        groups = _coerce_groups(payload, done_descriptions, detail_key="impact")
        return {
            "summary": _clean_task_line(payload.get("summary", "")) or f"{len(done_descriptions)} completed task(s) were grouped for {role}.",
            "headline": _clean_task_line(payload.get("headline", "")) or "Completed work",
            "chart": _coerce_chart(payload, groups, "Completed work"),
            "groups": groups,
            "insights": _coerce_list_of_strings(payload.get("insights"), limit=4),
        }

    def _analyze_pending(
        self,
        week_code: str,
        role: str,
        founder_name: str,
        pending_descriptions: list[str],
    ) -> dict[str, Any]:
        fallback_groups = _merge_buckets(pending_descriptions)
        fallback_chart = _coerce_chart({}, fallback_groups, "Carry-over work")
        payload = None
        if pending_descriptions:
            try:
                payload = self.runtime.reflection.generate_json_response(
                    system_prompt=WEEK_PWP_PENDING_ANALYSIS_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "week_code": week_code,
                            "role": role,
                            "founder_name": founder_name,
                            "pending_tasks": pending_descriptions,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    max_output_tokens=2500,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Pending-work synthesis failed; falling back to heuristics: %s", exc)

        blank_pages = DEFAULT_BLANK_PAGES
        if payload and isinstance(payload.get("blank_pages"), int):
            blank_pages = max(1, int(payload["blank_pages"]))

        if not payload:
            return {
                "summary": f"{len(pending_descriptions)} carry-over task(s) remain open for {role}.",
                "headline": "Carry-over work",
                "chart": fallback_chart,
                "groups": fallback_groups,
                "next_actions": [
                    "Review the open items and split any that are too broad.",
                    "Carry the remaining work into the next planning cycle.",
                ],
                "blank_pages": blank_pages,
            }

        groups = _coerce_groups(payload, pending_descriptions, detail_key="risk")
        return {
            "summary": _clean_task_line(payload.get("summary", "")) or f"{len(pending_descriptions)} carry-over task(s) remain open for {role}.",
            "headline": _clean_task_line(payload.get("headline", "")) or "Carry-over work",
            "chart": _coerce_chart(payload, groups, "Carry-over work"),
            "groups": groups,
            "next_actions": _coerce_list_of_strings(payload.get("next_actions"), limit=6)
            or [
                "Review the open items and split any that are too broad.",
                "Carry the remaining work into the next planning cycle.",
            ],
            "blank_pages": blank_pages,
        }

    def _compose_copy(
        self,
        week_code: str,
        role: str,
        founder_name: str,
        done_analysis: dict[str, Any],
        pending_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        payload = None
        try:
            payload = self.runtime.reflection.generate_json_response(
                system_prompt=WEEK_PWP_COMPOSE_PROMPT,
                user_prompt=json.dumps(
                    {
                        "week_code": week_code,
                        "role": role,
                        "founder_name": founder_name,
                        "done_summary": done_analysis.get("summary"),
                        "pending_summary": pending_analysis.get("summary"),
                        "done_groups": [group.get("title") for group in done_analysis.get("groups", [])],
                        "pending_groups": [group.get("title") for group in pending_analysis.get("groups", [])],
                        "pending_next_actions": pending_analysis.get("next_actions") or [],
                        "open_count": len(pending_analysis.get("groups", [])),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                max_output_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Cover copy synthesis failed; using fallback copy: %s", exc)

        cover = {
            "headline": f"Week {week_code.split('-W', 1)[1]} report",
            "subtitle": f"{role} · {founder_name}",
            "summary": done_analysis.get("summary") or pending_analysis.get("summary") or "Weekly report generated from completed and carry-over tasks.",
            "intro": "Completed work is grouped by theme, carry-over tasks are surfaced clearly, and the final section leaves blank pages for manual additions.",
        }
        next_week = {
            "headline": "Next week focus",
            "summary": pending_analysis.get("summary") or "Focus the next planning cycle on the open items below.",
            "bullets": pending_analysis.get("next_actions") or [],
        }

        if payload:
            cover_payload = payload.get("cover") if isinstance(payload.get("cover"), dict) else {}
            next_payload = payload.get("next_week") if isinstance(payload.get("next_week"), dict) else {}
            if cover_payload:
                cover.update(
                    {
                        "headline": _clean_task_line(cover_payload.get("headline", "")) or cover["headline"],
                        "subtitle": _clean_task_line(cover_payload.get("subtitle", "")) or cover["subtitle"],
                        "summary": _clean_task_line(cover_payload.get("summary", "")) or cover["summary"],
                        "intro": _clean_task_line(cover_payload.get("intro", "")) or cover["intro"],
                    }
                )
            if next_payload:
                next_week.update(
                    {
                        "headline": _clean_task_line(next_payload.get("headline", "")) or next_week["headline"],
                        "summary": _clean_task_line(next_payload.get("summary", "")) or next_week["summary"],
                        "bullets": _coerce_list_of_strings(next_payload.get("bullets"), limit=6) or next_week["bullets"],
                    }
                )

        return {"cover": cover, "next_week": next_week}

    def _assemble_plan(
        self,
        *,
        week_number: int,
        week_code: str,
        role: str,
        founder_name: str,
        person_query: str,
        all_tasks: list[dict[str, Any]],
        done_count: int,
        pending_count: int,
        done_analysis: dict[str, Any],
        pending_analysis: dict[str, Any],
        composition: dict[str, Any],
    ) -> dict[str, Any]:
        project_slug = _slugify(f"week-{week_number:02d}-{founder_name}-{role}-report")
        cover = composition["cover"]
        next_week = composition["next_week"]

        pages: list[dict[str, Any]] = [
            {
                "kind": "cover",
                "headline": cover["headline"],
                "subtitle": cover["subtitle"],
                "summary": cover["summary"],
                "intro": cover["intro"],
                "stats": [
                    {"number": done_count, "label": "completed tasks"},
                    {"number": pending_count, "label": "carry-over tasks"},
                    {"number": len(all_tasks), "label": "total tasks"},
                ],
                "chart": done_analysis.get("chart"),
                "footer": f"{week_code} · {role} · {founder_name}",
            },
            {"kind": "divider", "number": "01", "title": "Completed work", "darkBg": False},
        ]

        pages.extend(self._section_pages("Completed work", done_analysis))
        pages.append({"kind": "divider", "number": "02", "title": "Carry-over work", "darkBg": False})
        pages.extend(self._section_pages("Carry-over work", pending_analysis))
        pages.append({"kind": "divider", "number": "03", "title": "Next week", "darkBg": False})
        pages.append(
            {
                "kind": "next_week",
                "headline": next_week["headline"],
                "summary": next_week["summary"],
                "bullets": next_week["bullets"],
            }
        )
        for _ in range(max(1, int(pending_analysis.get("blank_pages") or DEFAULT_BLANK_PAGES))):
            pages.append({"kind": "blank"})

        return {
            "id": project_slug,
            "title": f"Week {week_number} report",
            "subtitle": f"{role} · {founder_name}",
            "week_code": week_code,
            "role": role,
            "founder_name": founder_name,
            "person_query": person_query,
            "counts": {
                "total": len(all_tasks),
                "done": done_count,
                "pending": pending_count,
            },
            "pages": pages,
        }

    def _section_pages(self, section_name: str, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        groups = analysis.get("groups", [])
        if not groups:
            groups = [{"title": "No tasks", "summary": f"No matching tasks were available for {section_name.lower()}.", "tasks": [], "detail": ""}]
        pages: list[dict[str, Any]] = []
        headline = analysis.get("headline") or section_name
        for index, chunk in enumerate(_split_groups(groups), start=1):
            title = headline if index == 1 else f"{headline} (cont.)"
            pages.append(
                {
                    "kind": "section",
                    "title": title,
                    "headline": title,
                    "summary": analysis.get("summary") or "",
                    "groups": chunk,
                    "chart": analysis.get("chart") if index == 1 else None,
                    "highlights": analysis.get("insights") or [] if index == 1 else [],
                }
            )
        return pages

    def _write_project(self, project_dir: Path, plan: dict[str, Any]) -> None:
        project_dir.mkdir(parents=True)
        self._write_text(project_dir / "package.json", json.dumps({
            "name": plan["id"],
            "version": "1.0.0",
            "type": "commonjs",
            "scripts": {"build": "node build.js"},
            "dependencies": {"pptxgenjs": "^4.0.1"},
        }, indent=2) + "\n")
        self._write_text(project_dir / "build.js", BUILD_JS_TEXT)
        self._write_text(project_dir / "Makefile", MAKEFILE_TEXT)
        self._write_text(project_dir / "deck.js", DECK_JS_TEXT)
        self._write_text(project_dir / "shared/theme.js", THEME_JS_TEXT)
        self._write_text(project_dir / "shared/helpers.js", HELPERS_JS_TEXT)
        update_sh = project_dir / "update.sh"
        self._write_text(update_sh, UPDATE_SH_TEXT.replace("{{NAME}}", plan["id"]))
        update_sh.chmod(update_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        data_js = "module.exports = " + json.dumps(plan, indent=2, ensure_ascii=False) + ";\n"
        self._write_text(project_dir / "data.js", data_js)
        self._write_readme(project_dir, plan)
        self._write_logo(project_dir / "assets" / "logo.png")
        (project_dir / "output" / "slides").mkdir(parents=True, exist_ok=True)

    def _write_readme(self, project_dir: Path, plan: dict[str, Any]) -> None:
        today = datetime.now(MADRID_TZ).date().isoformat()
        content = README_TEXT.format(
            title=plan["title"],
            today=today,
            week_number=plan["week_code"].split("-W", 1)[1],
            person_query=plan.get("person_query") or plan["role"],
            slug=plan["id"],
        )
        self._write_text(project_dir / "README.md", content)

    def _write_logo(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        repo_root = Path(__file__).resolve().parents[2]
        flux_logo = repo_root.parent / "flux" / "packages" / "flux-pwp" / "src" / "flux_pwp" / "templates" / "assets" / "logo.png"
        if flux_logo.exists():
            shutil.copy2(flux_logo, target)
            return
        target.write_bytes(_embedded_logo_bytes())

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
