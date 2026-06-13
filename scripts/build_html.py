#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_FILE = ROOT / "questions.md"
KEYWORDS_FILE = ROOT / "keywords.md"
ARTICLES_DIR = ROOT / "articles"
OUTPUT_FILE = ROOT / "docs" / "index.html"


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    published: bool


@dataclass(frozen=True)
class Article:
    id: str
    question: str
    body: str
    html: str
    tags: tuple[str, ...]


def parse_questions(path: Path) -> dict[str, Question]:
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^- \[(?P<status>[ xX])\] (?P<id>\d{4})\n  (?P<question>.+)$", re.MULTILINE)
    questions: dict[str, Question] = {}

    for match in pattern.finditer(content):
        article_id = match.group("id")
        if article_id in questions:
            raise ValueError(f"Duplicate question id in questions.md: {article_id}")
        questions[article_id] = Question(
            id=article_id,
            text=match.group("question").strip(),
            published=match.group("status").lower() == "x",
        )

    if not questions:
        raise ValueError("No questions found in questions.md")
    return questions


def parse_keywords(path: Path) -> list[str]:
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if match:
            keywords.append(match.group(1).strip().lower())
    return keywords


def split_front_matter(path: Path) -> tuple[dict[str, str], str]:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.match(r"^---\n(?P<meta>.*?)\n---\n?(?P<body>.*)$", content, re.DOTALL)
    if not match:
        raise ValueError(f"Article has no front matter: {path}")

    meta: dict[str, str] = {}
    for line in match.group("meta").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, match.group("body").strip()


def format_inline(text: str) -> str:
    code_parts: list[str] = []

    def save_code(match: re.Match[str]) -> str:
        code_parts.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\u0000CODE{len(code_parts) - 1}\u0000"

    text = re.sub(r"`([^`]+)`", save_code, text)
    escaped = html.escape(text)

    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<em>\1</em>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)
    escaped = re.sub(r"\|\|(.+?)\|\|", r'<span class="spoiler">\1</span>', escaped)

    def link_url(match: re.Match[str]) -> str:
        url = match.group(0)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>'

    escaped = re.sub(r"https?://[^\s<]+", link_url, escaped)

    def link_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        return f'<button class="tag-link" type="button" data-tag="{html.escape(tag)}">{tag}</button>'

    escaped = re.sub(r"(?<![\wА-Яа-яЁё])#[\wА-Яа-яЁё]+", link_tag, escaped)

    for index, code in enumerate(code_parts):
        escaped = escaped.replace(f"\u0000CODE{index}\u0000", code)

    return escaped


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    ordered_items: list[str] = []
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(f"<p>{format_inline(' '.join(part.strip() for part in paragraph))}</p>")
            paragraph = []

    def flush_lists() -> None:
        nonlocal list_items, ordered_items
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items = []
        if ordered_items:
            blocks.append("<ol>" + "".join(f"<li>{item}</li>" for item in ordered_items) + "</ol>")
            ordered_items = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                flush_lists()
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            flush_lists()
            continue

        bullet = re.match(r"^-\s+(.+)$", stripped)
        ordered = re.match(r"^\d+\.\s+(.+)$", stripped)

        if bullet:
            flush_paragraph()
            if ordered_items:
                flush_lists()
            list_items.append(format_inline(bullet.group(1)))
            continue

        if ordered:
            flush_paragraph()
            if list_items:
                flush_lists()
            ordered_items.append(format_inline(ordered.group(1)))
            continue

        flush_lists()
        paragraph.append(line)

    flush_paragraph()
    flush_lists()
    if in_code:
        blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")

    return "\n".join(blocks)


def article_tags(markdown: str) -> tuple[str, ...]:
    tags = sorted({match.group(0).lower() for match in re.finditer(r"(?<![\wА-Яа-яЁё])#[\wА-Яа-яЁё]+", markdown)})
    return tuple(tags)


def load_articles(questions: dict[str, Question]) -> list[Article]:
    articles: list[Article] = []
    for path in sorted(ARTICLES_DIR.glob("*.md")):
        meta, body = split_front_matter(path)
        article_id = meta.get("id")
        question = meta.get("question")

        if not article_id or not question:
            raise ValueError(f"Article must contain id and question: {path}")
        if path.stem != article_id:
            raise ValueError(f"Article filename and id differ: {path}")
        if article_id not in questions:
            raise ValueError(f"Article has no matching question in questions.md: {path}")
        if questions[article_id].text != question:
            raise ValueError(f"Question text differs for {article_id}")

        articles.append(
            Article(
                id=article_id,
                question=question,
                body=body,
                html=markdown_to_html(body),
                tags=article_tags(body),
            )
        )
    return articles


def build_page(articles: list[Article], keywords: list[str]) -> str:
    nav_items = "\n".join(
        f'<a class="nav-item" href="#q-{article.id}" data-target="q-{article.id}">'
        f'<span>{article.id}</span>{html.escape(article.question)}</a>'
        for article in articles
    )
    article_cards = "\n".join(
        f"""
        <article class="article" id="q-{article.id}" data-id="{article.id}" data-question="{html.escape(article.question)}">
          <header class="article-header">
            <p class="article-id">#{article.id}</p>
            <h2>{html.escape(article.question)}</h2>
            <a class="anchor" href="#q-{article.id}" aria-label="Ссылка на вопрос {article.id}">#</a>
          </header>
          <div class="article-body">{article.html}</div>
        </article>
        """.strip()
        for article in articles
    )

    data = {
        "keywords": keywords,
        "articleCount": len(articles),
    }

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Meshtastic39 FAQ</title>
  <meta name="description" content="Краткая база знаний Meshtastic для Калининградского сообщества">
  <script>
    (() => {{
      let saved = null;
      try {{
        saved = localStorage.getItem('faq-theme');
      }} catch (error) {{}}
      const theme = saved || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      document.documentElement.dataset.theme = theme;
    }})();
  </script>
  <style>
    :root {{
      --bg: #ffffff;
      --surface: #ffffff;
      --surface-soft: #f5f6f7;
      --surface-hover: rgba(0, 0, 0, 0.05);
      --text: #1c1e21;
      --text-strong: #1c1e21;
      --muted: #525860;
      --line: #dadde1;
      --accent: #2e8555;
      --accent-strong: #277148;
      --code-bg: #f6f7f8;
      --code-text: var(--text-strong);
      --code-border: rgba(0, 0, 0, 0.10);
      --pre-bg: #f6f7f8;
      --pre-text: var(--text);
      --mark: rgba(255, 215, 142, 0.45);
      --mark-current: #67ea94;
      --topbar: rgba(255, 255, 255, 0.86);
      --shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.10);
      color-scheme: light;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, Cantarell, "Noto Sans", sans-serif, BlinkMacSystemFont, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
    }}

    html[data-theme="dark"] {{
      --bg: #1b1b1d;
      --surface: #242526;
      --surface-soft: #303541;
      --surface-hover: rgba(255, 255, 255, 0.08);
      --text: #e3e3e3;
      --text-strong: #ffffff;
      --muted: #bfc7d5;
      --line: #303541;
      --accent: #67ea94;
      --accent-strong: #67ea94;
      --code-bg: rgba(255, 255, 255, 0.10);
      --code-text: #ffffff;
      --code-border: rgba(0, 0, 0, 0.10);
      --pre-bg: #292d3e;
      --pre-text: #bfc7d5;
      --mark: rgba(255, 215, 142, 0.25);
      --mark-current: rgba(103, 234, 148, 0.45);
      --topbar: rgba(10, 12, 15, 0.85);
      --shadow: 0 5px 40px rgba(0, 0, 0, 0.20);
      color-scheme: dark;
    }}

    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-size: 16px;
      line-height: 1.65;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizelegibility;
    }}

    a {{ color: var(--accent-strong); text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    button, input {{ font: inherit; }}

    .topbar {{
      position: sticky;
      top: 0;
      z-index: 30;
      border-bottom: 1px solid var(--line);
      background: var(--topbar);
      backdrop-filter: blur(12px);
    }}

    .topbar-inner {{
      display: grid;
      grid-template-columns: minmax(210px, 280px) minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      max-width: 1280px;
      margin: 0 auto;
      padding: 9px 24px;
    }}

    .brand {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}

    .brand strong {{ font-size: 18px; line-height: 1.2; }}
    .brand span {{ color: var(--muted); font-size: 13px; }}

    .top-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}

    .menu-button {{
      display: none;
      position: relative;
      width: 42px;
      height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
    }}

    .menu-button span,
    .menu-button::before,
    .menu-button::after {{
      position: absolute;
      left: 11px;
      width: 18px;
      height: 2px;
      border-radius: 999px;
      background: currentColor;
      content: "";
    }}

    .menu-button span {{ top: 20px; }}
    .menu-button::before {{ top: 14px; }}
    .menu-button::after {{ top: 26px; }}

    .menu-button:hover {{ border-color: var(--accent); color: var(--accent-strong); }}

    .theme-button {{
      display: inline-grid;
      place-items: center;
      width: 42px;
      height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
    }}

    .theme-button:hover {{
      border-color: var(--accent);
      color: var(--accent-strong);
      background: var(--surface-hover);
    }}

    .theme-icon {{
      width: 20px;
      height: 20px;
      fill: currentColor;
    }}

    html[data-theme="light"] #themeIconMoon,
    html[data-theme="dark"] #themeIconSun {{
      display: none;
    }}

    .search {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto auto;
      gap: 8px;
      align-items: center;
    }}

    .search input {{
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 14px;
      background: var(--surface);
      color: var(--text);
      outline: none;
    }}

    .search input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(22, 122, 85, 0.14);
    }}

    .search-count {{
      min-width: 74px;
      color: var(--muted);
      font-size: 14px;
      text-align: center;
    }}

    .icon-button {{
      width: 42px;
      height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
    }}

    .icon-button:hover {{ border-color: var(--accent); color: var(--accent-strong); }}

    .layout {{
      display: grid;
      grid-template-columns: minmax(210px, 280px) minmax(0, 1fr);
      gap: 24px;
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}

    .sidebar {{
      position: sticky;
      top: 82px;
      align-self: start;
      min-width: 0;
      max-height: calc(100vh - 104px);
      overflow: auto;
      padding: 8px 8px 8px 0;
    }}

    .mobile-menu-backdrop {{
      display: none;
    }}

    .nav-title {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
    }}

    .nav-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}

    .nav-item {{
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 6px 12px;
      border-radius: 6px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.35;
      text-decoration: none;
    }}

    .nav-item span {{
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }}

    .nav-item:hover, .nav-item.active {{
      background: var(--surface-hover);
      color: var(--accent-strong);
    }}

    .content {{
      min-width: 0;
      padding-bottom: 40px;
    }}

    .intro {{
      margin: 0 0 18px;
      color: var(--muted);
    }}

    .article {{
      scroll-margin-top: 92px;
      margin-bottom: 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .article-header {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
      padding: 18px 22px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }}

    .article-id {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}

    .article h2 {{
      margin: 0;
      color: var(--text-strong);
      font-size: 24px;
      font-weight: 700;
      line-height: 1.25;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }}

    .anchor {{
      display: inline-grid;
      place-items: center;
      width: 32px;
      height: 32px;
      border-radius: 6px;
      color: var(--muted);
      text-decoration: none;
    }}

    .anchor:hover {{
      background: var(--surface-soft);
      color: var(--accent-strong);
    }}

    .article-body {{
      padding: 18px 22px 22px;
      max-width: 860px;
      overflow-wrap: anywhere;
    }}

    .article-body p {{ margin: 0 0 16px; }}
    .article-body p:last-child {{ margin-bottom: 0; }}
    .article-body ul, .article-body ol {{ margin: 0 0 14px 22px; padding: 0; }}
    .article-body li {{ margin: 4px 0; }}
    .article-body code {{
      padding: 0.1rem;
      border: 1px solid var(--code-border);
      border-radius: 0.4rem;
      background: var(--code-bg);
      color: var(--code-text);
      font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 1rem;
      font-weight: 600;
      line-height: 1.6;
      vertical-align: middle;
    }}
    .article-body pre {{
      overflow: auto;
      border-radius: 6px;
      background: var(--pre-bg);
      color: var(--pre-text);
      font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 1rem;
      line-height: 1.75;
      margin: 0 0 1rem;
      padding: 0;
    }}
    .article-body pre code {{
      display: block;
      padding: 1rem;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      font-weight: 400;
      line-height: inherit;
      white-space: pre;
    }}

    .tag-link {{
      display: inline;
      border: 0;
      padding: 0;
      background: transparent;
      color: var(--accent-strong);
      cursor: pointer;
      text-decoration: underline;
      text-decoration-thickness: 1px;
      text-underline-offset: 3px;
    }}

    mark.search-hit {{
      padding: 1px 2px;
      border-radius: 3px;
      background: var(--mark);
      color: inherit;
    }}

    mark.search-hit.current {{
      background: var(--mark-current);
      outline: 2px solid rgba(22, 122, 85, 0.28);
    }}

    .spoiler {{
      border-radius: 4px;
      background: var(--line);
      color: transparent;
      cursor: default;
    }}
    .spoiler:hover {{ color: inherit; }}

    .empty-state {{
      display: none;
      padding: 24px;
      border: 1px dashed var(--line);
      border-radius: 6px;
      color: var(--muted);
      background: var(--surface);
    }}

    .empty-state.visible {{ display: block; }}

    @media (max-width: 860px) {{
      .topbar-inner {{
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        padding: 12px 16px;
      }}

      .top-actions {{
        grid-column: 2;
        grid-row: 1;
      }}

      .menu-button {{
        display: inline-grid;
        place-items: center;
      }}

      .search {{
        grid-column: 1 / -1;
      }}

      .layout {{
        grid-template-columns: 1fr;
        padding: 16px;
      }}

      .sidebar {{
        position: fixed;
        top: 0;
        right: 0;
        bottom: 0;
        z-index: 50;
        display: flex;
        flex-direction: column;
        width: min(360px, calc(100vw - 48px));
        height: 100vh;
        height: 100dvh;
        max-height: 100vh;
        max-height: 100dvh;
        padding: 18px 14px 18px 18px;
        overflow: hidden;
        border-left: 1px solid var(--line);
        background: var(--surface);
        box-shadow: var(--shadow);
        transform: translateX(100%);
        transition: transform 160ms ease;
      }}

      .mobile-menu-open .sidebar {{
        transform: translateX(0);
      }}

      .nav-list {{
        flex-direction: column;
        flex: 1;
        gap: 8px;
        min-height: 0;
        overflow-y: auto;
        overscroll-behavior: contain;
        padding-bottom: 20px;
        -webkit-overflow-scrolling: touch;
      }}

      .nav-item {{
        min-width: 0;
        padding: 11px 10px;
        border: 1px solid var(--line);
        background: var(--surface);
      }}

      .mobile-menu-backdrop {{
        display: block;
        position: fixed;
        inset: 0;
        z-index: 49;
        background: rgba(0, 0, 0, 0.40);
        opacity: 0;
        pointer-events: none;
        transition: opacity 160ms ease;
      }}

      .mobile-menu-open .mobile-menu-backdrop {{
        opacity: 1;
        pointer-events: auto;
      }}

      .mobile-menu-open {{
        overflow: hidden;
      }}

      .article {{
        scroll-margin-top: 132px;
      }}
    }}

    @media (max-width: 560px) {{
      body {{ font-size: 15px; }}

      .search {{
        grid-template-columns: 1fr auto auto;
      }}

      .search-count {{
        grid-column: 1 / -1;
        min-width: 0;
        text-align: left;
      }}

      .article-header {{
        grid-template-columns: 1fr auto;
        padding: 16px 16px 12px;
      }}

      .article-id {{
        grid-column: 1 / -1;
        margin: 0;
      }}

      .article h2 {{ font-size: 19px; }}
      .article-body {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <strong>Meshtastic39 FAQ</strong>
        <span>{len(articles)} вопросов и ответов</span>
      </div>
      <div class="top-actions">
        <button class="theme-button" id="themeButton" type="button" aria-label="Переключить тему">
          <svg class="theme-icon" id="themeIconSun" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6Zm0-8a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0V2a1 1 0 0 1 1-1Zm0 18a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0v-2a1 1 0 0 1 1-1ZM4.22 3.8a1 1 0 0 1 1.41 0l1.42 1.42a1 1 0 0 1-1.42 1.41L4.22 5.22a1 1 0 0 1 0-1.42Zm12.73 12.73a1 1 0 0 1 1.42 0l1.41 1.42a1 1 0 0 1-1.41 1.41l-1.42-1.41a1 1 0 0 1 0-1.42ZM1 12a1 1 0 0 1 1-1h2a1 1 0 1 1 0 2H2a1 1 0 0 1-1-1Zm18 0a1 1 0 0 1 1-1h2a1 1 0 1 1 0 2h-2a1 1 0 0 1-1-1ZM7.05 16.95a1 1 0 0 1 0 1.42l-1.42 1.41a1 1 0 0 1-1.41-1.41l1.41-1.42a1 1 0 0 1 1.42 0ZM19.78 4.22a1 1 0 0 1 0 1.41l-1.41 1.42a1 1 0 0 1-1.42-1.42l1.42-1.41a1 1 0 0 1 1.41 0Z"/></svg>
          <svg class="theme-icon" id="themeIconMoon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9.37 5.51A7.5 7.5 0 0 0 18.49 14.63 7 7 0 1 1 9.37 5.51ZM12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a1 1 0 0 0-1.65-.55 5.5 5.5 0 0 1-7.34-7.34 1 1 0 0 0-.55-1.65A9.1 9.1 0 0 0 12 3Z"/></svg>
        </button>
        <button class="menu-button" id="menuButton" type="button" aria-label="Открыть список вопросов" aria-controls="questionNav" aria-expanded="false"><span></span></button>
      </div>
      <div class="search" role="search">
        <input id="searchInput" type="search" autocomplete="off" placeholder="Поиск по статьям, например #антенна">
        <button class="icon-button" id="prevHit" type="button" aria-label="Предыдущее совпадение">↑</button>
        <button class="icon-button" id="nextHit" type="button" aria-label="Следующее совпадение">↓</button>
        <span class="search-count" id="searchCount">0 / 0</span>
      </div>
    </div>
  </header>

  <div class="mobile-menu-backdrop" id="mobileMenuBackdrop"></div>

  <main class="layout">
    <aside class="sidebar" id="questionNav" aria-label="Список вопросов">
      <p class="nav-title">Вопросы</p>
      <nav class="nav-list">
        {nav_items}
      </nav>
    </aside>

    <section class="content" aria-label="Ответы">
      <div class="empty-state" id="emptyState">Совпадений не найдено.</div>
      {article_cards}
    </section>
  </main>

  <script type="application/json" id="pageData">{html.escape(json.dumps(data, ensure_ascii=False))}</script>
  <script>
    const searchInput = document.querySelector('#searchInput');
    const prevButton = document.querySelector('#prevHit');
    const nextButton = document.querySelector('#nextHit');
    const searchCount = document.querySelector('#searchCount');
    const emptyState = document.querySelector('#emptyState');
    const menuButton = document.querySelector('#menuButton');
    const themeButton = document.querySelector('#themeButton');
    const themeIconSun = document.querySelector('#themeIconSun');
    const themeIconMoon = document.querySelector('#themeIconMoon');
    const mobileMenuBackdrop = document.querySelector('#mobileMenuBackdrop');
    const articles = [...document.querySelectorAll('.article')];
    const navItems = [...document.querySelectorAll('.nav-item')];
    const markClass = 'search-hit';
    let hits = [];
    let currentHit = -1;

    function setMenuOpen(open) {{
      document.body.classList.toggle('mobile-menu-open', open);
      menuButton.setAttribute('aria-expanded', String(open));
      menuButton.setAttribute('aria-label', open ? 'Закрыть список вопросов' : 'Открыть список вопросов');
    }}

    function setTheme(theme) {{
      document.documentElement.dataset.theme = theme;
      try {{
        localStorage.setItem('faq-theme', theme);
      }} catch (error) {{}}
      const isDark = theme === 'dark';
      themeIconSun.style.display = isDark ? 'none' : 'block';
      themeIconMoon.style.display = isDark ? 'block' : 'none';
      themeButton.setAttribute('aria-label', isDark ? 'Включить светлую тему' : 'Включить тёмную тему');
      themeButton.setAttribute('title', isDark ? 'Светлая тема' : 'Тёмная тема');
    }}

    function escapeRegExp(value) {{
      return value.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
    }}

    function clearHighlights(root) {{
      root.querySelectorAll('mark.' + markClass).forEach((mark) => {{
        mark.replaceWith(document.createTextNode(mark.textContent));
      }});
      root.normalize();
    }}

    function highlightTextNode(node, regex) {{
      const text = node.nodeValue;
      if (!regex.test(text)) return;
      regex.lastIndex = 0;

      const fragment = document.createDocumentFragment();
      let lastIndex = 0;
      let match;
      while ((match = regex.exec(text)) !== null) {{
        if (match.index > lastIndex) {{
          fragment.append(document.createTextNode(text.slice(lastIndex, match.index)));
        }}
        const mark = document.createElement('mark');
        mark.className = markClass;
        mark.textContent = match[0];
        fragment.append(mark);
        lastIndex = match.index + match[0].length;
      }}
      if (lastIndex < text.length) {{
        fragment.append(document.createTextNode(text.slice(lastIndex)));
      }}
      node.replaceWith(fragment);
    }}

    function highlight(root, query) {{
      const regex = new RegExp(escapeRegExp(query), 'giu');
      const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_TEXT,
        {{
          acceptNode(node) {{
            const parent = node.parentElement;
            if (!parent || parent.closest('script, style, mark')) return NodeFilter.FILTER_REJECT;
            if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
          }}
        }}
      );

      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach((node) => highlightTextNode(node, regex));
    }}

    function setCurrentHit(index, scroll = true) {{
      hits.forEach((hit) => hit.classList.remove('current'));
      if (!hits.length) {{
        currentHit = -1;
        searchCount.textContent = '0 / 0';
        return;
      }}
      currentHit = (index + hits.length) % hits.length;
      hits[currentHit].classList.add('current');
      searchCount.textContent = `${{currentHit + 1}} / ${{hits.length}}`;
      if (scroll) hits[currentHit].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    }}

    function updateSearch(scroll = true) {{
      const query = searchInput.value.trim();
      articles.forEach(clearHighlights);
      hits = [];
      currentHit = -1;

      if (query) {{
        articles.forEach((article) => highlight(article, query));
        hits = [...document.querySelectorAll('mark.' + markClass)];
      }}

      emptyState.classList.toggle('visible', Boolean(query) && hits.length === 0);
      setCurrentHit(0, Boolean(query) && scroll);
    }}

    function setSearch(value) {{
      searchInput.value = value;
      updateSearch(true);
      searchInput.focus();
    }}

    document.addEventListener('click', (event) => {{
      const tag = event.target.closest('.tag-link');
      if (tag) {{
        setSearch(tag.dataset.tag);
      }}

      const navItem = event.target.closest('.nav-item');
      if (navItem) {{
        setMenuOpen(false);
      }}
    }});

    menuButton.addEventListener('click', () => {{
      setMenuOpen(!document.body.classList.contains('mobile-menu-open'));
    }});
    themeButton.addEventListener('click', () => {{
      const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      setTheme(current === 'dark' ? 'light' : 'dark');
    }});
    mobileMenuBackdrop.addEventListener('click', () => setMenuOpen(false));
    window.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') setMenuOpen(false);
    }});

    searchInput.addEventListener('input', () => updateSearch(true));
    nextButton.addEventListener('click', () => setCurrentHit(currentHit + 1, true));
    prevButton.addEventListener('click', () => setCurrentHit(currentHit - 1, true));

    const observer = new IntersectionObserver((entries) => {{
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      navItems.forEach((item) => item.classList.toggle('active', item.dataset.target === visible.target.id));
    }}, {{ rootMargin: '-20% 0px -65% 0px', threshold: [0.1, 0.3, 0.6] }});

    articles.forEach((article) => observer.observe(article));
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');

    window.addEventListener('hashchange', () => {{
      const target = document.querySelector(window.location.hash);
      if (target) target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Meshtastic39 FAQ HTML page")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="Output HTML file")
    args = parser.parse_args()

    questions = parse_questions(QUESTIONS_FILE)
    keywords = parse_keywords(KEYWORDS_FILE)
    articles = load_articles(questions)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_page(articles, keywords), encoding="utf-8")
    print(f"Built {args.output} from {len(articles)} articles")


if __name__ == "__main__":
    main()
