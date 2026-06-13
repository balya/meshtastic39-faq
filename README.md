# Meshtastic39 FAQ

Страница FAQ: https://balya.github.io/meshtastic39-faq/

---

Краткая база знаний и FAQ по Meshtastic для Telegram-группы Калининградского сообщества: https://t.me/meshtastic_39

Проект хранит ответы на частые вопросы участников: от первых шагов и выбора устройств до MQTT, антенн, ограничений сети и практических настроек.

## Структура

- `questions.md` — список вопросов и статусы статей.
- `articles/` — отдельные ответы по идентификаторам вопросов.
- `knowledge.md` — проверенные знания и рекомендации сообщества.
- `keywords.md` — ключевые слова для хештегов в Telegram.
- `scripts/build_html.py` — сборка статей в статическую HTML-страницу.
- `.github/workflows/pages.yml` — сборка и публикация GitHub Pages.

Материалы пишутся кратко, практически и с опорой на официальную документацию Meshtastic и опыт сообщества.

## Сборка HTML

```bash
python3 scripts/build_html.py
```

После сборки откройте `docs/index.html` в браузере.
