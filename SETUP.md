# SETUP — полная настройка с нуля (≈40-60 минут)

Гайд для запуска конвейера на чистой машине (Linux или macOS).
Иди по шагам сверху вниз, ничего не пропускай.

## Шаг 0. Что понадобится (аккаунты и деньги)

| Сервис | Зачем | Тариф |
|---|---|---|
| [ElevenLabs](https://elevenlabs.io) | озвучка | Starter ($5/мес) хватает |
| [Google AI Studio](https://aistudio.google.com/apikey) | тайминги фраз, чекеры | бесплатный ключ |
| [Higgsfield](https://higgsfield.ai) | кадры + анимация Kling | Creator (~$35/мес, 6000 кредитов; ролик ≈ 50-70 кредитов) |
| [Claude](https://claude.com/claude-code) | сценарист и раскадровщик | подписка Pro/Max |
| GitHub | этот репозиторий | — |

## Шаг 1. Системные зависимости

```bash
# macOS
brew install ffmpeg python@3.11 node git
# Ubuntu/Debian
sudo apt install -y ffmpeg python3.11 python3.11-venv nodejs npm git
```

Проверка: `ffmpeg -version && ffprobe -version && python3 --version`

## Шаг 2. Репозиторий и Python-окружение

```bash
git clone <ссылка-на-этот-репозиторий>
cd meaning-video-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # нужен для рендера превью (опционально)
```

## Шаг 3. Ключи

```bash
cp .env.example .env
```

1. **ElevenLabs**: Profile → API Keys → создать → вписать в `ELEVENLABS_API_KEY`.
   Голос: зайди в Voice Library, выбери голос (наш пример — Sergey,
   `XuEV9VY3VUASYgJVNBh0`), вставь его ID в `MEANING_VOICE_ID`.
2. **Gemini**: https://aistudio.google.com/apikey → Create API key →
   в `GEMINI_API_KEY`.
3. Загрузка окружения перед любым запуском:
   `set -a; source .env; set +a`

## Шаг 4. Higgsfield CLI

```bash
npm install -g higgsfield
higgsfield auth          # логин через браузер
higgsfield account status --json   # должно показать кредиты
```

## Шаг 5. Claude CLI

```bash
npm install -g @anthropic-ai/claude-code
claude                   # первый запуск = авторизация
claude -p "скажи ок"     # проверка headless-режима
```

## Шаг 6. Папки и файлы данных

```bash
mkdir -p ~/meaning_factory_work ~/music_library ~/.aiplus-factory
echo '{}' > ~/.aiplus-factory/tts_pronun.json
```

- **~/music_library/** — положи 3-5 своих mp3-треков (сборщик берёт трек и
  сам стартует его с дропа). Без треков сборка упадёт.
- **tts_pronun.json** — словарь ударений для TTS: `{"Айплюс": "Айплю́с"}`
  (акут = символ U+0301 после ударной гласной; работает только с моделью
  eleven_multilingual_v2). Можно оставить пустым `{}` и пополнять по мере
  появления слов, которые голос читает неправильно.

## Шаг 7. Пути в скриптах

Скрипты берут корень от домашней папки (`Path.home()`), поэтому на новой
машине почти всё заведётся само. Проверь три константы под себя:

- `scripts/meaning_factory.py`: `TRACK` (какой mp3 использовать), `CTA_CARD`
  (png финального слайда с призывом — сделай свой или закомментируй cta-план),
  блок Postgres (см. Шаг 9).
- `scripts/meaning_writer.py`: `BRIDGES`, `CODEBOOK` — пути к docs/ (положи
  `docs/meaning_bridges.md` туда, куда указывает путь, или поправь путь).
- `scripts/gen_voice_v7.py`: путь к тексту и выходной папке.

## Шаг 8. Первый прогон (проверка всех узлов по одному)

```bash
set -a; source .env; set +a

# 1. Озвучка — самый быстрый smoke-тест ключей ElevenLabs
python scripts/gen_voice_v7.py            # появится mp3 → послушай

# 2. Тайминги — тест Gemini
python scripts/phrase_times_sergey.py     # напечатает фразы с таймингами

# 3. Кадр — тест Higgsfield (потратит 1-2 кредита)
higgsfield generate create nano_banana --prompt "test noir frame, golden light" \
  --aspect_ratio 9:16 --wait --json

# 4. Сценарист — тест Claude CLI
python scripts/meaning_writer.py --topic "Дисциплина у ребёнка" --route "В2"
```

Если все четыре отработали — конвейер жив.

## Шаг 9. Полный ролик

Вариант А (рекомендуемый для старта) — по шагам руками:
озвучка → тайминги → раскадровка+генерация+сборка из `meaning_factory.py`
(функции `tts_sergey`, `phrase_times`, `shotlist`, `gen_shot`, `assemble` —
можно звать из своего скрипта без БД).

Вариант Б — автозавод `meaning_factory.py` как есть: требует Postgres с
таблицей story_videos (наша вкладка-CRM). Если базы нет — закомментируй
блок `main()` c SQL и подавай сценарий напрямую в `process_card`-цепочку.

## Типичные грабли (мы их уже прошли — не повторяй)

1. Kling-промпт с двумя действиями → брак. Одно движение + статичная камера.
2. Замедление реальных 25fps-футажей → дёрганое месиво. Тянуть можно только
   почти-статичные ИИ-планы.
3. Тайминги Gemini без рамки длительности → выдуманный хронометраж.
   В скриптах рамка уже вшита — не убирай ретраи.
4. Смена словаря ударений ПОСЛЕ генерации озвучки меняет кеш-ключ — правь
   словарь до, а не после.
5. ИИ-лица крупным планом палятся. Силуэты, спины, руки, предметы.
6. Музыка с начала трека = 20 секунд вступления. Сборщик сам ищет дроп —
   не отключай.
7. Higgsfield иногда предлагает свои пресеты вместо твоего промпта — в CLI
   этого нет, но в API передавай declined_preset_id при повторе.
